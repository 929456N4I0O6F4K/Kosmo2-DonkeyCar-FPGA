package main

import (
	"archive/zip"
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"io"
	"math"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func testApp(t *testing.T) *App {
	t.Helper()
	b := newSimulator()
	a := &App{backend: b, dataRoot: t.TempDir(), maxThrottle: .25}
	ctx, cancel := context.WithCancel(context.Background())
	a.start(ctx)
	t.Cleanup(func() { cancel(); a.wg.Wait(); a.setRecording(false); b.Close() })
	until(t, func() bool { a.mu.Lock(); defer a.mu.Unlock(); return !a.lastFrame.IsZero() })
	return a
}
func until(t *testing.T, f func() bool) {
	t.Helper()
	end := time.Now().Add(3 * time.Second)
	for time.Now().Before(end) {
		if f() {
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatal("condition timed out")
}
func request(t *testing.T, a *App, method, path, body string) *httptest.ResponseRecorder {
	t.Helper()
	r := httptest.NewRequest(method, path, strings.NewReader(body))
	r.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	a.handler().ServeHTTP(w, r)
	return w
}
func TestControlValidationLatestInputAndTimeout(t *testing.T) {
	a := testApp(t)
	r := DriveRequest{Client: "driver-001", Sequence: 1, Gesture: 1, Enable: true, Angle: -.3, Throttle: .1}
	if err := a.drive(r); err != nil {
		t.Fatal(err)
	}
	if err := a.drive(r); err == nil {
		t.Fatal("replayed command accepted")
	}
	other := r
	other.Client = "driver-002"
	if err := a.drive(other); err != nil {
		t.Fatal("latest controller input rejected", err)
	}
	r.Sequence++
	r.Throttle = math.NaN()
	if a.drive(r) == nil {
		t.Fatal("NaN accepted")
	}
	r.Throttle = .8
	if a.drive(r) == nil {
		t.Fatal("throttle cap ignored")
	}
	until(t, func() bool { a.mu.Lock(); defer a.mu.Unlock(); return a.latest.Flags&enabledFlag != 0 })
	time.Sleep(400 * time.Millisecond)
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.latest.Flags != 0 || a.latest.Throttle != 0 {
		t.Fatal("lease loss did not stop")
	}
}

func TestAnyPageCanStopOrChangeInput(t *testing.T) {
	a := testApp(t)
	first := DriveRequest{Client: "driver-001", Sequence: 1, Gesture: 1, Enable: true, Throttle: .1}
	if err := a.drive(first); err != nil {
		t.Fatal(err)
	}
	second := DriveRequest{Client: "driver-002", Sequence: 1, Gesture: 1, Enable: true, Angle: .2, Throttle: .2}
	if err := a.drive(second); err != nil {
		t.Fatal(err)
	}
	a.mu.Lock()
	desired := a.desired
	a.mu.Unlock()
	if desired.Angle != .2 || desired.Throttle != .2 {
		t.Fatal("latest input was not applied")
	}
	first.Sequence++
	first.Enable = false
	if err := a.drive(first); err != nil {
		t.Fatal("stop from another page rejected", err)
	}
	a.mu.Lock()
	enabled := a.desired.Enable
	a.mu.Unlock()
	if enabled {
		t.Fatal("stop ignored")
	}
}
func TestNetworkVideoRecordingAndDownload(t *testing.T) {
	a := testApp(t)
	if w := request(t, a, "GET", "/api/status", ""); w.Code != 200 {
		t.Fatal(w.Code)
	}
	if w := request(t, a, "POST", "/api/drive", `{"client":"driver-001","sequence":1,"enable":true,"angle":0,"throttle":0.1,"unknown":1}`); w.Code != 400 {
		t.Fatal("unknown field accepted")
	}
	if w := request(t, a, "POST", "/api/record", `{"recording":true}`); w.Code != 200 {
		t.Fatal(w.Body.String())
	}
	for i := 1; i <= 12; i++ {
		body := `{"client":"driver-001","gesture":1,"sequence":` + stringNumber(i) + `,"enable":true,"angle":-0.25,"throttle":0.12}`
		if w := request(t, a, "POST", "/api/drive", body); w.Code != 200 {
			t.Fatal(w.Body.String())
		}
		time.Sleep(50 * time.Millisecond)
	}
	if w := request(t, a, "GET", "/api/download", ""); w.Code != 409 {
		t.Fatal("active session download allowed")
	}
	if err := a.setRecording(false); err != nil {
		t.Fatal(err)
	}
	w := request(t, a, "GET", "/api/download", "")
	if w.Code != 200 {
		t.Fatal(w.Code)
	}
	z, err := zip.NewReader(bytes.NewReader(w.Body.Bytes()), int64(w.Body.Len()))
	if err != nil {
		t.Fatal(err)
	}
	if len(z.File) < 4 {
		t.Fatal("missing dataset files")
	}
	data, err := os.ReadFile(filepath.Join(a.dataRoot, a.lastSession, "records.jsonl"))
	if err != nil {
		t.Fatal(err)
	}
	scanner := bufio.NewScanner(bytes.NewReader(data))
	count := 0
	for scanner.Scan() {
		var r map[string]any
		if err = json.Unmarshal(scanner.Bytes(), &r); err != nil {
			t.Fatal(err)
		}
		if r["user/angle"] != -.25 || r["user/throttle"] != .12 {
			t.Fatal("misaligned labels")
		}
		count++
	}
	if count < 4 {
		t.Fatalf("only %d records", count)
	}
	summaryData, err := os.ReadFile(filepath.Join(a.dataRoot, a.lastSession, "recording-summary.json"))
	if err != nil {
		t.Fatal(err)
	}
	var summary RecordingIO
	if err = json.Unmarshal(summaryData, &summary); err != nil || summary.Saved != uint64(count) || summary.Queued != 0 || !summary.Closed {
		t.Fatal("incomplete recording summary", summary, err)
	}
	// Exercise an actual TCP HTTP stream; a slow viewer cannot own control locks.
	server := httptest.NewServer(a.handler())
	defer server.Close()
	req, _ := http.NewRequest("GET", server.URL+"/video.mjpg", nil)
	response, err := (&http.Client{Timeout: 2 * time.Second}).Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	reader := bufio.NewReader(response.Body)
	line, err := reader.ReadString('\n')
	if err != nil || !strings.Contains(line, "--frame") {
		t.Fatal("missing MJPEG boundary", err)
	}
}
func stringNumber(i int) string { data, _ := json.Marshal(i); return string(data) }
func TestCrossOriginRejected(t *testing.T) {
	a := testApp(t)
	r := httptest.NewRequest("POST", "http://car/api/drive", strings.NewReader("{}"))
	r.Header.Set("Origin", "http://other")
	w := httptest.NewRecorder()
	a.handler().ServeHTTP(w, r)
	if w.Code != 403 {
		t.Fatal(w.Code)
	}
}

type stalledBackend struct{ *Simulator }

func (b stalledBackend) Next(ctx context.Context) (Frame, error) {
	<-ctx.Done()
	return Frame{}, ctx.Err()
}
func TestCameraStallStopsControl(t *testing.T) {
	b := stalledBackend{newSimulator()}
	a := &App{backend: b, maxThrottle: .25, lastFrame: time.Now(), desired: DriveRequest{Client: "driver-001", Sequence: 1, Enable: true, Throttle: .1}, lastInput: time.Now()}
	ctx, cancel := context.WithCancel(context.Background())
	a.start(ctx)
	defer func() { cancel(); a.wg.Wait(); b.Close() }()
	time.Sleep(1100 * time.Millisecond)
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.fault == "" || a.desired.Enable {
		t.Fatal("camera fault not latched")
	}
}
func TestRecordingSessionIsolation(t *testing.T) {
	a := testApp(t)
	a.setRecording(true)
	first := a.lastSession
	a.setRecording(false)
	a.setRecording(true)
	if first == a.lastSession {
		t.Fatal("session overwritten")
	}
	f, err := os.Open(filepath.Join(a.dataRoot, first, "records.jsonl"))
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	data, _ := io.ReadAll(f)
	if len(data) != 0 {
		t.Fatal("stationary uncommanded frames recorded")
	}
}

type healthBackend struct {
	*Simulator
	health map[string]bool
}

func (b healthBackend) Health() map[string]bool { return b.health }
func TestActuatorReadinessBlocksEnableButAllowsStop(t *testing.T) {
	for _, health := range []map[string]bool{
		{"ready": false}, {"ready": true, "armed": false}, {"ready": true, "armed": true, "fault": true},
		{"ready": true, "armed": true, "shutdown_unconfirmed": true},
	} {
		b := healthBackend{newSimulator(), health}
		a := &App{backend: b, maxThrottle: 1, lastFrame: time.Now()}
		r := DriveRequest{Client: "driver-001", Sequence: 1, Gesture: 1, Enable: true}
		if a.drive(r) == nil {
			t.Fatal("enable accepted before healthy all-off state", health)
		}
		r.Enable = false
		if err := a.drive(r); err != nil {
			t.Fatal("stop blocked", err)
		}
		b.Close()
	}
}

func TestReconnectRequiresNewPress(t *testing.T) {
	a := testApp(t)
	r := DriveRequest{Client: "driver-001", Sequence: 1, Gesture: 1, Enable: true, Throttle: .1}
	if err := a.drive(r); err != nil {
		t.Fatal(err)
	}
	time.Sleep(400 * time.Millisecond)
	r.Sequence++
	if a.drive(r) == nil {
		t.Fatal("delayed heartbeat resumed driving")
	}
	r.Enable = false
	if err := a.drive(r); err != nil {
		t.Fatal(err)
	}
	r.Sequence++
	r.Enable = true
	if a.drive(r) == nil {
		t.Fatal("old press accepted after release")
	}
	r.Gesture++
	if err := a.drive(r); err != nil {
		t.Fatal("fresh press rejected", err)
	}
}
