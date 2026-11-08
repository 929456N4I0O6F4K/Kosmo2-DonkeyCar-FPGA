package main

import (
	"bufio"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"
)

func TestSlowRecordingDoesNotBlockVideoControlStatusOrStop(t *testing.T) {
	a := testApp(t)
	gate := make(chan struct{})
	entered := make(chan struct{})
	var first, release sync.Once
	r := &Recorder{id: "slow-disk"}
	r.startWriter(func(Frame) error { first.Do(func() { close(entered); <-gate }); return nil }, func() error { return nil })
	t.Cleanup(func() { release.Do(func() { close(gate) }); r.Close() })
	a.recordMu.Lock()
	a.recorder = r
	a.lastSession = r.id
	a.mu.Lock()
	a.recording = true
	a.mu.Unlock()
	a.recordMu.Unlock()
	req := DriveRequest{Client: "slow-disk-test", Gesture: 1, Enable: true, Throttle: .1}
	send := func() {
		req.Sequence++
		if err := a.drive(req); err != nil {
			t.Fatal(err)
		}
	}
	send()
	select {
	case <-entered:
	case <-time.After(time.Second):
		t.Fatal("writer never received a frame")
	}
	start := a.status()
	server := httptest.NewServer(a.handler())
	defer server.Close()
	client := &http.Client{Timeout: 300 * time.Millisecond}
	response, err := client.Get(server.URL + "/video.mjpg")
	if err != nil {
		t.Fatal("blocked disk stalled live MJPEG", err)
	}
	line, err := bufio.NewReader(response.Body).ReadString('\n')
	response.Body.Close()
	if err != nil || !strings.Contains(line, "--frame") {
		t.Fatal("no live MJPEG", line, err)
	}
	// Hold storage long enough to exhaust the bounded queue, while renewing input.
	end := time.Now().Add(2500 * time.Millisecond)
	for time.Now().Before(end) {
		send()
		response, err = client.Get(server.URL + "/api/status")
		if err != nil {
			t.Fatal("status waited for disk", err)
		}
		response.Body.Close()
		time.Sleep(40 * time.Millisecond)
	}
	s := a.status()
	stats := s["recording_io"].(RecordingIO)
	if s["fault"] != "" || s["frame_age_ms"].(int64) >= 500 || s["command_ack"].(uint32) <= start["command_ack"].(uint32)+10 || s["frame"].(Frame).Sequence <= start["frame"].(Frame).Sequence+10 {
		t.Fatal("disk blocked live processing", s)
	}
	if stats.Queued != recordingQueueFrames || stats.Dropped == 0 || stats.Saved != 0 || stats.WriteAgeMS < 2000 {
		t.Fatal("unbounded, hidden, or untested backlog", stats)
	}
	stopDone := make(chan error, 1)
	go func() { stopDone <- a.setRecording(false) }()
	until(t, func() bool { return a.status()["record_closing"].(bool) })
	if a.setRecording(true) == nil {
		t.Fatal("new session allowed during flush")
	}
	if w := request(t, a, "GET", "/api/download", ""); w.Code != 409 {
		t.Fatal("incomplete session downloaded")
	}
	req.Enable = false
	send()
	until(t, func() bool { return a.status()["frame"].(Frame).Flags == 0 })
	if s := a.status(); s["fault"] != "" || s["frame_age_ms"].(int64) >= 500 {
		t.Fatal("flush blocked stop/video", s)
	}
	release.Do(func() { close(gate) })
	if err = <-stopDone; err != nil {
		t.Fatal(err)
	}
	s = a.status()
	stats = s["recording_io"].(RecordingIO)
	if s["record_open"].(bool) || stats.Queued != 0 || stats.Saved != recordingQueueFrames+1 {
		t.Fatal("accepted frames not drained", s)
	}
}

func TestRecordingFailureDoesNotLatchCameraOrControlFault(t *testing.T) {
	a := testApp(t)
	r := &Recorder{id: "full-disk"}
	r.startWriter(func(Frame) error { return errors.New("disk full") }, func() error { return nil })
	t.Cleanup(func() { r.Close() })
	a.recordMu.Lock()
	a.recorder = r
	a.mu.Lock()
	a.recording = true
	a.mu.Unlock()
	a.recordMu.Unlock()
	req := DriveRequest{Client: "disk-error-test", Gesture: 1, Enable: true, Throttle: .1}
	for i := 0; i < 8; i++ {
		req.Sequence++
		if err := a.drive(req); err != nil {
			t.Fatal(err)
		}
		time.Sleep(40 * time.Millisecond)
	}
	until(t, func() bool { return !a.status()["recording"].(bool) })
	s := a.status()
	if s["fault"] != "" || !strings.Contains(s["recording_error"].(string), "disk full") || s["frame_age_ms"].(int64) >= 500 {
		t.Fatal(s)
	}
	req.Sequence++
	if err := a.drive(req); err != nil {
		t.Fatal("storage failure blocked healthy live control", err)
	}
	if err := a.setRecording(false); err == nil {
		t.Fatal("storage failure hidden on close")
	}
	if a.status()["record_open"].(bool) {
		t.Fatal("failed session not released")
	}
}

func TestRecordingQueueOwnsImageAndLabels(t *testing.T) {
	gate := make(chan struct{})
	entered := make(chan struct{})
	written := make(chan Frame, 2)
	var first sync.Once
	r := &Recorder{}
	r.startWriter(func(f Frame) error { first.Do(func() { close(entered); <-gate }); written <- f; return nil }, func() error { return nil })
	f := Frame{Sequence: 1, Angle: -.2, Throttle: .1, RGB: []byte{1, 2, 3}}
	if err := r.Enqueue(f); err != nil {
		t.Fatal(err)
	}
	<-entered
	f.RGB[0] = 99
	f.Sequence = 2
	f.Angle = .7
	if err := r.Enqueue(f); err != nil {
		t.Fatal(err)
	}
	f.RGB[0] = 0
	close(gate)
	if err := r.Close(); err != nil {
		t.Fatal(err)
	}
	a, b := <-written, <-written
	if a.RGB[0] != 1 || a.Sequence != 1 || a.Angle != -.2 || b.RGB[0] != 99 || b.Sequence != 2 || b.Angle != .7 {
		t.Fatal("image or label changed while queued", a, b)
	}
}
