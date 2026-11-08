package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"image/png"
	"os"
	"path/filepath"
	"sync"
	"time"
)

type Recorder struct {
	path                    string
	file                    *os.File
	count                   uint64
	id                      string
	mu                      sync.Mutex
	queue                   chan Frame
	done                    chan struct{}
	closing                 bool
	closed                  bool
	err                     error
	dropped                 uint64
	writeStart              time.Time
	lastWriteMS, maxWriteMS int64
}

const recordingQueueFrames = 32 // <= 1.9 MiB RGB plus one frame being written.

type RecordingIO struct {
	Saved       uint64 `json:"saved"`
	Queued      int    `json:"queued"`
	Capacity    int    `json:"capacity"`
	Dropped     uint64 `json:"dropped"`
	Closing     bool   `json:"closing"`
	Closed      bool   `json:"closed"`
	Writing     bool   `json:"writing"`
	WriteAgeMS  int64  `json:"write_age_ms"`
	LastWriteMS int64  `json:"last_write_ms"`
	MaxWriteMS  int64  `json:"max_write_ms"`
	Error       string `json:"error"`
}

func newRecorder(root, source string, steering SteeringSettings, exposure ...ExposureSettings) (*Recorder, error) {
	id := time.Now().UTC().Format("20060102T150405.000000000Z") + "_" + randomID(4)
	dir := filepath.Join(root, id)
	if err := os.MkdirAll(filepath.Join(dir, "images"), 0755); err != nil {
		return nil, err
	}
	metadata := map[string]any{"schema": "kosmo-training-v1", "session_id": id, "source": source, "synthetic": source == "simulation", "created_utc": time.Now().UTC(), "width": width, "height": height, "color": "RGB", "angle_convention": "-1 left, +1 right", "throttle_convention": "0 stopped, +1 forward", "label_kind": "control-core accepted setpoint at frame start; not physical feedback", "clock": "PA 50MHz ticks converted to microseconds; simulation monotonic clock", "preprocessing": "preserve 120x160 RGB; model crops rows 25:120, columns 2:158"}
	metadata["steering"] = steering.info()
	metadata["recording_buffer"] = map[string]any{"capacity_frames": recordingQueueFrames, "overflow": "skip incoming recording frame; live capture continues", "durability": "image sync, then record sync for each saved frame"}
	if len(exposure) > 0 {
		metadata["exposure"] = exposure[0].resolved()
	}
	data, _ := json.MarshalIndent(metadata, "", "  ")
	if err := os.WriteFile(filepath.Join(dir, "session.json"), data, 0644); err != nil {
		return nil, err
	}
	f, err := os.OpenFile(filepath.Join(dir, "records.jsonl"), os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0644)
	if err != nil {
		return nil, err
	}
	r := &Recorder{path: dir, file: f, id: id}
	r.startWriter(r.writeFrame, f.Close)
	return r, nil
}

// The sole worker owns file I/O. No application or queue lock spans disk writes.
func (r *Recorder) startWriter(write func(Frame) error, closeFile func() error) {
	r.queue = make(chan Frame, recordingQueueFrames)
	r.done = make(chan struct{})
	go func() {
		defer close(r.done)
		defer func() {
			err := closeFile()
			r.mu.Lock()
			if r.err == nil {
				r.err = err
			}
			r.closed = true
			r.mu.Unlock()
			if r.path != "" {
				data, _ := json.MarshalIndent(r.Stats(), "", "  ")
				if err := os.WriteFile(filepath.Join(r.path, "recording-summary.json"), data, 0644); err != nil {
					r.mu.Lock()
					if r.err == nil {
						r.err = fmt.Errorf("recording summary: %w", err)
					}
					r.mu.Unlock()
				}
			}
		}()
		failed := false
		for frame := range r.queue {
			if failed {
				r.mu.Lock()
				r.dropped++
				r.mu.Unlock()
				continue
			}
			start := time.Now()
			r.mu.Lock()
			r.writeStart = start
			r.mu.Unlock()
			err := write(frame)
			ms := time.Since(start).Milliseconds()
			r.mu.Lock()
			r.writeStart = time.Time{}
			r.lastWriteMS = ms
			if ms > r.maxWriteMS {
				r.maxWriteMS = ms
			}
			if err != nil {
				r.err = err
				r.dropped++
				failed = true
			} else {
				r.count++
			}
			r.mu.Unlock()
		}
	}()
}

// Enqueue without waiting for disk. Frames and their original labels stay paired.
func (r *Recorder) Enqueue(frame Frame) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.err != nil {
		return r.err
	}
	if r.closing {
		return errors.New("recording is closing")
	}
	if len(r.queue) == cap(r.queue) {
		r.dropped++
		return nil
	}
	frame.RGB = append([]byte(nil), frame.RGB...)
	r.queue <- frame
	return nil
}

func (r *Recorder) Stats() RecordingIO {
	r.mu.Lock()
	defer r.mu.Unlock()
	s := RecordingIO{Saved: r.count, Queued: len(r.queue), Capacity: cap(r.queue), Dropped: r.dropped, Closing: r.closing && !r.closed, Closed: r.closed,
		Writing: !r.writeStart.IsZero(), LastWriteMS: r.lastWriteMS, MaxWriteMS: r.maxWriteMS}
	if s.Writing {
		s.WriteAgeMS = time.Since(r.writeStart).Milliseconds()
	}
	if r.err != nil {
		s.Error = r.err.Error()
	}
	return s
}

func (r *Recorder) writeFrame(frame Frame) error {
	name := fmt.Sprintf("images/%010d.png", frame.Sequence)
	p := filepath.Join(r.path, filepath.FromSlash(name))
	f, err := os.OpenFile(p, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0644)
	if err != nil {
		return err
	}
	err = (&png.Encoder{CompressionLevel: png.BestSpeed}).Encode(f, frame.Image())
	if err == nil {
		err = f.Sync()
	}
	closeErr := f.Close()
	if err == nil {
		err = closeErr
	}
	if err != nil {
		return err
	}
	received := frame.ReceivedUTC
	if received.IsZero() {
		received = time.Now().UTC()
	}
	record := map[string]any{"cam/image_array": name, "user/angle": frame.Angle, "user/throttle": frame.Throttle, "user/mode": "user", "session_id": r.id, "frame_sequence": frame.Sequence, "capture_us": frame.CaptureUS, "command_sequence": frame.CommandSequence, "source_dropped": frame.Dropped, "received_utc": received.Format(time.RFC3339Nano)}
	if err = json.NewEncoder(r.file).Encode(record); err != nil {
		return err
	}
	// Images precede records; interruption may leave an orphan image, never a
	// successful record pointing at a partially written image.
	if err = r.file.Sync(); err != nil {
		return err
	}
	return nil
}
func (r *Recorder) Close() error {
	r.mu.Lock()
	if !r.closing {
		r.closing = true
		close(r.queue)
	}
	r.mu.Unlock()
	<-r.done // Drain admitted frames; caller holds no capture/status/control lock.
	r.mu.Lock()
	defer r.mu.Unlock()
	return r.err
}
