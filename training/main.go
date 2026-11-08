package main

import (
	"archive/zip"
	"bytes"
	"context"
	"crypto/rand"
	"embed"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"image/jpeg"
	"io"
	"io/fs"
	"log"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"sync"
	"syscall"
	"time"
)

//go:embed web/*
var webFiles embed.FS

const lease = 300 * time.Millisecond

type DriveRequest struct {
	Client   string  `json:"client"`
	Sequence uint64  `json:"sequence"`
	Gesture  uint64  `json:"gesture"` // new physical press; unchanged during heartbeats
	Enable   bool    `json:"enable"`
	Angle    float64 `json:"angle"`
	Throttle float64 `json:"throttle"`
}
type App struct {
	backend              Backend
	dataRoot             string
	maxThrottle          float64
	steering             SteeringSettings
	steeringPath         string
	exposure             ExposureSettings
	exposurePath         string
	exposureBusy         bool
	frameCount           uint64
	mu                   sync.Mutex
	desired              DriveRequest
	blockedClient        string
	blockedGesture       uint64
	lastInput, lastFrame time.Time
	latest               Frame
	preview              []byte
	ack                  uint32
	recording            bool
	fault                string
	recordMu             sync.Mutex
	recordOpMu           sync.Mutex
	recordClosing        bool
	recordOpening        bool
	recordIO             RecordingIO
	recordError          string
	recorder             *Recorder
	minRecordSeq         uint32
	saved                uint64
	lastSession          string
	wg                   sync.WaitGroup
}

func randomID(n int) string {
	b := make([]byte, n)
	if _, e := rand.Read(b); e != nil {
		panic(e)
	}
	return hex.EncodeToString(b)
}
func (a *App) fail(err error) {
	a.mu.Lock()
	a.fault = err.Error()
	a.desired.Enable = false
	a.recording = false
	a.mu.Unlock()
	log.Print(err)
}
func (a *App) start(ctx context.Context) {
	a.wg.Add(2)
	go func() { defer a.wg.Done(); a.capture(ctx) }()
	go func() { defer a.wg.Done(); a.controls(ctx) }()
}
func (a *App) controls(ctx context.Context) {
	tick := time.NewTicker(50 * time.Millisecond)
	defer tick.Stop()
	for {
		select {
		case <-ctx.Done():
			stopCtx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
			_, err := a.backend.Apply(stopCtx, Command{})
			cancel()
			if err != nil {
				log.Printf("final stop unconfirmed: %v", err)
			}
			return
		case now := <-tick.C:
			a.mu.Lock()
			c := Command{}
			if a.fault == "" && !a.exposureBusy && a.desired.Enable && now.Sub(a.lastInput) < lease && now.Sub(a.lastFrame) < 500*time.Millisecond {
				c = Command{Angle: a.desired.Angle, Throttle: a.desired.Throttle, Flags: enabledFlag}
				if a.recording {
					c.Flags |= recordFlag
				}
			} else {
				if a.desired.Enable {
					a.blockedClient, a.blockedGesture = a.desired.Client, a.desired.Gesture
				}
				a.desired.Enable = false
			}
			c.Steering = a.steering.resolved()
			a.mu.Unlock()
			applyCtx, cancel := context.WithTimeout(ctx, 80*time.Millisecond)
			seq, err := a.backend.Apply(applyCtx, c)
			cancel()
			if err != nil {
				if ctx.Err() == nil {
					a.fail(fmt.Errorf("control acknowledgement: %w", err))
				}
				continue
			}
			a.mu.Lock()
			a.ack = seq
			a.mu.Unlock()
		}
	}
}
func (a *App) capture(ctx context.Context) {
	var lastUS uint64
	var lastSeq uint32
	for {
		frameCtx, cancel := context.WithTimeout(ctx, time.Second)
		f, err := a.backend.Next(frameCtx)
		cancel()
		if err != nil {
			if ctx.Err() == nil {
				a.fail(fmt.Errorf("camera: %w", err))
			}
			return
		}
		if err = f.Validate(); err != nil {
			a.fail(err)
			return
		}
		if lastSeq != 0 && (f.Sequence == lastSeq || f.CaptureUS <= lastUS) {
			a.fail(errors.New("duplicate frame or capture clock reset; restart collector"))
			return
		}
		lastSeq, lastUS = f.Sequence, f.CaptureUS
		f.ReceivedUTC = time.Now().UTC()
		var buf bytes.Buffer
		if err = jpeg.Encode(&buf, f.Image(), &jpeg.Options{Quality: 80}); err != nil {
			a.fail(err)
			return
		}
		a.mu.Lock()
		a.latest = f
		a.frameCount++
		a.lastFrame = time.Now()
		a.preview = buf.Bytes()
		a.mu.Unlock()
		a.recordMu.Lock()
		a.mu.Lock()
		recording := a.recording
		a.mu.Unlock()
		if recording && a.recorder != nil && f.Flags&recordFlag != 0 && int32(f.CommandSequence-a.minRecordSeq) >= 0 {
			if err = a.recorder.Enqueue(f); err != nil {
				a.mu.Lock()
				a.recording = false
				a.recordError = err.Error()
				a.mu.Unlock()
				log.Printf("recording stopped; live video/control continue: %v", err)
			}
		}
		a.recordMu.Unlock()
	}
}
func (a *App) drive(r DriveRequest) error {
	if len(r.Client) < 8 || len(r.Client) > 128 || r.Sequence == 0 || (r.Enable && r.Gesture == 0) || !validCommand(Command{Angle: r.Angle, Throttle: r.Throttle}) || r.Throttle > a.maxThrottle {
		return errors.New("invalid control input or throttle limit exceeded")
	}
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.desired.Enable && time.Since(a.lastInput) >= lease {
		a.blockedClient, a.blockedGesture = a.desired.Client, a.desired.Gesture
		a.desired.Enable = false
	}
	if r.Enable && r.Client == a.blockedClient && r.Gesture <= a.blockedGesture {
		return errors.New("control timed out; release and press again")
	}
	if r.Enable && (a.exposureBusy || a.fault != "" || time.Since(a.lastFrame) > 500*time.Millisecond) {
		return errors.New("fresh video and healthy backend required")
	}
	if h, ok := a.backend.(interface{ Health() map[string]bool }); ok && r.Enable {
		v := h.Health()
		if !v["ready"] || !v["armed"] || v["fault"] || v["shutdown_unconfirmed"] {
			return errors.New("actuator controller is not ready")
		}
	}
	if a.desired.Client == r.Client {
		if r.Sequence <= a.desired.Sequence {
			return errors.New("out-of-order control command")
		}
	}
	// No browser ownership: the latest valid input is applied, including stops.
	a.desired = r
	a.lastInput = time.Now()
	return nil
}
func (a *App) setRecording(on bool) error {
	// A slow close must not serialize status, capture or drive requests.
	if !a.recordOpMu.TryLock() {
		return errors.New("recording is being opened or saved; try again shortly")
	}
	defer a.recordOpMu.Unlock()
	return a.changeRecording(on)
}

func (a *App) closeRecording() error {
	a.recordOpMu.Lock()
	defer a.recordOpMu.Unlock()
	return a.changeRecording(false)
}

func (a *App) changeRecording(on bool) error {
	a.recordMu.Lock()
	a.mu.Lock()
	if on && (a.fault != "" || a.exposureBusy) {
		a.mu.Unlock()
		a.recordMu.Unlock()
		return errors.New("backend fault")
	}
	a.recording = false
	minSeq := a.ack + 2
	steering := a.steering.resolved()
	exposure := a.exposure.resolved()
	r := a.recorder
	a.recordClosing = r != nil
	a.recordOpening = on
	a.mu.Unlock()
	a.recordMu.Unlock()
	defer func() { a.mu.Lock(); a.recordOpening = false; a.mu.Unlock() }()
	if r != nil {
		err := r.Close()
		a.recordMu.Lock()
		a.recordIO = r.Stats()
		a.saved = a.recordIO.Saved
		a.recorder = nil
		a.mu.Lock()
		a.recordClosing = false
		if err != nil {
			a.recordError = err.Error()
		}
		a.mu.Unlock()
		a.recordMu.Unlock()
		if err != nil {
			return err
		}
	}
	if on {
		r, err := newRecorder(a.dataRoot, a.backend.Name(), steering, exposure)
		if err != nil {
			return err
		}
		a.recordMu.Lock()
		a.recorder = r
		a.minRecordSeq = minSeq
		a.saved = 0
		a.lastSession = r.id
		a.mu.Lock()
		a.recordError = ""
		a.recording = true
		a.mu.Unlock()
		a.recordMu.Unlock()
	}
	return nil
}
func (a *App) status() map[string]any {
	a.recordMu.Lock()
	defer a.recordMu.Unlock()
	a.mu.Lock()
	defer a.mu.Unlock()
	age := int64(-1)
	if !a.lastFrame.IsZero() {
		age = time.Since(a.lastFrame).Milliseconds()
	}
	stats := a.recordIO
	if a.recorder != nil {
		stats = a.recorder.Stats()
	}
	result := map[string]any{"backend": a.backend.Name(), "frame": a.latest, "frame_age_ms": age, "recording": a.recording, "record_open": a.recorder != nil || a.recordOpening, "record_opening": a.recordOpening, "record_closing": a.recordClosing, "recording_io": stats, "recording_error": a.recordError, "saved": stats.Saved, "session": a.lastSession, "enabled": a.desired.Enable && time.Since(a.lastInput) < lease, "command_ack": a.ack, "fault": a.fault, "max_throttle": a.maxThrottle}
	result["steering"] = a.steering.info()
	result["exposure"] = a.exposureInfo()
	if h, ok := a.backend.(interface{ Health() map[string]bool }); ok {
		result["controller"] = h.Health()
	}
	return result
}
func writeJSON(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(v)
}
func decodeJSON(w http.ResponseWriter, r *http.Request, v any) error {
	if !strings.HasPrefix(r.Header.Get("Content-Type"), "application/json") {
		return errors.New("application/json required")
	}
	dec := json.NewDecoder(http.MaxBytesReader(w, r.Body, 4096))
	dec.DisallowUnknownFields()
	if err := dec.Decode(v); err != nil {
		return err
	}
	var extra any
	if dec.Decode(&extra) != io.EOF {
		return errors.New("trailing JSON")
	}
	return nil
}
func (a *App) handler() http.Handler {
	mux := http.NewServeMux()
	web, _ := fs.Sub(webFiles, "web")
	mux.Handle("/", http.FileServer(http.FS(web)))
	mux.HandleFunc("GET /api/status", func(w http.ResponseWriter, r *http.Request) { writeJSON(w, a.status()) })
	mux.HandleFunc("POST /api/exposure", func(w http.ResponseWriter, r *http.Request) {
		var body ExposureSettings
		if err := decodeJSON(w, r, &body); err != nil {
			http.Error(w, err.Error(), 400)
			return
		}
		if err := body.validate(); err != nil {
			http.Error(w, err.Error(), 400)
			return
		}
		if err := a.setExposure(body); err != nil {
			http.Error(w, err.Error(), 409)
			return
		}
		writeJSON(w, a.status())
	})
	mux.HandleFunc("POST /api/steering", func(w http.ResponseWriter, r *http.Request) {
		var body SteeringSettings
		if err := decodeJSON(w, r, &body); err != nil {
			http.Error(w, err.Error(), 400)
			return
		}
		if err := body.validate(); err != nil {
			http.Error(w, err.Error(), 400)
			return
		}
		if err := a.setSteering(body); err != nil {
			http.Error(w, err.Error(), 409)
			return
		}
		writeJSON(w, a.status())
	})
	mux.HandleFunc("POST /api/drive", func(w http.ResponseWriter, r *http.Request) {
		var body DriveRequest
		if err := decodeJSON(w, r, &body); err != nil {
			http.Error(w, err.Error(), 400)
			return
		}
		if err := a.drive(body); err != nil {
			http.Error(w, err.Error(), 409)
			return
		}
		writeJSON(w, map[string]bool{"accepted": true})
	})
	mux.HandleFunc("POST /api/record", func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Recording bool `json:"recording"`
		}
		if err := decodeJSON(w, r, &body); err != nil {
			http.Error(w, err.Error(), 400)
			return
		}
		if err := a.setRecording(body.Recording); err != nil {
			http.Error(w, err.Error(), 409)
			return
		}
		writeJSON(w, a.status())
	})
	mux.HandleFunc("GET /video.mjpg", a.video)
	mux.HandleFunc("GET /api/download", a.download)
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Cache-Control", "no-store")
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("Content-Security-Policy", "default-src 'self'; img-src 'self'; frame-ancestors 'none'")
		if r.Method == "POST" {
			if origin := r.Header.Get("Origin"); origin != "" {
				u, err := url.Parse(origin)
				if err != nil || u.Host != r.Host {
					http.Error(w, "cross-origin request", 403)
					return
				}
			}
		}
		mux.ServeHTTP(w, r)
	})
}
func (a *App) video(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "multipart/x-mixed-replace; boundary=frame")
	tick := time.NewTicker(time.Second / 30)
	defer tick.Stop()
	var last uint32
	rc := http.NewResponseController(w)
	for {
		select {
		case <-r.Context().Done():
			return
		case <-tick.C:
		}
		a.mu.Lock()
		seq := a.latest.Sequence
		data := a.preview
		fresh := time.Since(a.lastFrame) < 500*time.Millisecond
		a.mu.Unlock()
		if !fresh || last == seq || len(data) == 0 {
			continue
		}
		last = seq
		rc.SetWriteDeadline(time.Now().Add(time.Second))
		if _, err := fmt.Fprintf(w, "--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\nX-Frame-Sequence: %d\r\n\r\n", len(data), seq); err != nil {
			return
		}
		if _, err := w.Write(data); err != nil {
			return
		}
		if _, err := w.Write([]byte("\r\n")); err != nil {
			return
		}
		if err := rc.Flush(); err != nil {
			return
		}
	}
}
func (a *App) download(w http.ResponseWriter, r *http.Request) {
	a.recordMu.Lock()
	id := a.lastSession
	a.mu.Lock()
	active := a.recorder != nil || a.recordOpening
	a.mu.Unlock()
	a.recordMu.Unlock()
	if id == "" || active {
		http.Error(w, "stop recording before downloading", 409)
		return
	}
	root := filepath.Join(a.dataRoot, id)
	w.Header().Set("Content-Type", "application/zip")
	w.Header().Set("Content-Disposition", `attachment; filename="`+id+`.zip"`)
	z := zip.NewWriter(w)
	err := filepath.WalkDir(root, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.IsDir() {
			return nil
		}
		if !d.Type().IsRegular() {
			return errors.New("non-regular dataset file")
		}
		rel, err := filepath.Rel(root, path)
		if err != nil {
			return err
		}
		dst, err := z.CreateHeader(&zip.FileHeader{Name: id + "/" + filepath.ToSlash(rel), Method: zip.Store})
		if err != nil {
			return err
		}
		src, err := os.Open(path)
		if err != nil {
			return err
		}
		defer src.Close()
		_, err = io.Copy(dst, src)
		return err
	})
	if err != nil {
		log.Printf("download interrupted: %v", err)
	}
	z.Close()
}
func main() {
	backendName := flag.String("backend", "sim", "sim or uio")
	device := flag.String("uio", "/dev/uio0", "verified shared DDR UIO device")
	listen := flag.String("listen", "127.0.0.1:8080", "HTTP address; PU: 0.0.0.0:8080")
	data := flag.String("data", "data", "recording directory")
	maxThrottle := flag.Float64("max-throttle", .25, "normalized forward throttle limit")
	steeringPath := flag.String("steering-config", "", "saved steering settings; default: steering.json beside data directory")
	exposurePath := flag.String("exposure-config", "", "saved exposure settings; default: exposure.json beside data directory")
	flag.Parse()
	if !validCommand(Command{Throttle: *maxThrottle}) || *maxThrottle <= 0 {
		log.Fatal("max-throttle must be in (0,1]")
	}
	var b Backend
	var err error
	if *steeringPath == "" {
		*steeringPath = filepath.Join(filepath.Dir(*data), "steering.json")
	}
	steering, err := loadSteering(*steeringPath)
	if err != nil {
		log.Fatal("steering settings: ", err)
	}
	if *exposurePath == "" {
		*exposurePath = filepath.Join(filepath.Dir(*data), "exposure.json")
	}
	exposure, err := loadExposure(*exposurePath)
	if err != nil {
		log.Fatal("exposure settings: ", err)
	}
	switch *backendName {
	case "sim":
		b = newSimulator()
	case "uio":
		b, err = openUIO(*device)
	default:
		log.Fatal("unknown backend")
	}
	if err != nil {
		log.Fatal(err)
	}
	defer b.Close()
	a := &App{backend: b, dataRoot: *data, maxThrottle: *maxThrottle, steering: steering, steeringPath: *steeringPath, exposure: exposure, exposurePath: *exposurePath}
	// Initial disabled command must be acknowledged before opening the service.
	initCtx, initCancel := context.WithTimeout(context.Background(), time.Second)
	a.ack, err = b.Apply(initCtx, Command{Steering: steering})
	initCancel()
	if err != nil {
		log.Fatal(err)
	}
	if supportsExposure(b) {
		exposureCtx, exposureCancel := context.WithTimeout(context.Background(), time.Second)
		err = b.(exposureBackend).ApplyExposure(exposureCtx, exposure)
		exposureCancel()
		if err != nil {
			log.Fatal("initial exposure configuration: ", err)
		}
	} else if exposure.Mode != "auto" {
		log.Fatal("saved manual exposure requires FPGA ABI 3; run full deployment")
	} else {
		log.Print("legacy FPGA: live video/recording supported; exposure controls need full v8 upgrade")
	}
	listener, err := net.Listen("tcp", *listen)
	if err != nil {
		log.Fatal(err)
	}
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	a.start(ctx)
	server := &http.Server{Handler: a.handler(), ReadHeaderTimeout: 3 * time.Second, ReadTimeout: 3 * time.Second, IdleTimeout: 15 * time.Second, MaxHeaderBytes: 8192}
	log.Printf("backend=%s; open http://%s/", b.Name(), listener.Addr())
	done := make(chan error, 1)
	go func() { done <- server.Serve(listener) }()
	select {
	case <-ctx.Done():
	case err = <-done:
		if !errors.Is(err, http.ErrServerClosed) {
			log.Print(err)
		}
		cancel()
	}
	shutdown, c := context.WithTimeout(context.Background(), 2*time.Second)
	defer c()
	server.Shutdown(shutdown)
	server.Close()
	a.wg.Wait()
	if err = a.closeRecording(); err != nil {
		log.Print(err)
	}
}
