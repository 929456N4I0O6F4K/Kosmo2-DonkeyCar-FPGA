package main

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestExposureValidationPersistenceAndPacking(t *testing.T) {
	path := filepath.Join(t.TempDir(), "exposure.json")
	if got, err := loadExposure(path); err != nil || got != defaultExposure() {
		t.Fatal(got, err)
	}
	for _, s := range []ExposureSettings{{"manual", 0}, {"manual", 1200}, {"auto", 300}} {
		commit, cleanup, err := stageExposure(path, s)
		if err != nil {
			t.Fatal(err)
		}
		if err = commit(); err != nil {
			t.Fatal(err)
		}
		cleanup()
		if got, err := loadExposure(path); err != nil || got != s {
			t.Fatal(got, err)
		}
		if s.packed()&2047 != uint32(s.Value) || ((s.packed()>>31) != 0) != (s.Mode == "auto") {
			t.Fatal("mailbox packing", s)
		}
	}
	for _, text := range []string{`{}`, `null`, `{"mode":"manual","value":1201}`, `{"mode":"manual","value":-1}`, `{"mode":"auto","value":300,"extra":1}`, `{"mode":"manual","value":1.5}`, `{"mode":"manual","value":300} {}`} {
		os.WriteFile(path, []byte(text), 0600)
		if _, err := loadExposure(path); err == nil {
			t.Fatal("invalid config accepted", text)
		}
	}
}
func TestExposureAPIModesRecordingAndNoActuation(t *testing.T) {
	a := testApp(t)
	a.exposurePath = filepath.Join(t.TempDir(), "exposure.json")
	for _, body := range []string{`{"mode":"manual","value":300}`, `{"mode":"manual","value":1200}`, `{"mode":"auto","value":300}`} {
		w := request(t, a, "POST", "/api/exposure", body)
		if w.Code != 200 {
			t.Fatal(w.Code, w.Body.String())
		}
		var expected ExposureSettings
		json.Unmarshal([]byte(body), &expected)
		loaded, err := loadExposure(a.exposurePath)
		if err != nil || loaded != expected {
			t.Fatal(loaded, err)
		}
		a.backend.(*Simulator).mu.Lock()
		actual := a.backend.(*Simulator).exposure
		cmd := a.backend.(*Simulator).cmd
		a.backend.(*Simulator).mu.Unlock()
		if actual != expected || cmd.Flags != 0 || cmd.Angle != 0 || cmd.Throttle != 0 {
			t.Fatal("camera settings enabled drive or differ", actual, cmd)
		}
	}
	if w := request(t, a, "POST", "/api/exposure", `{"mode":"manual","value":1201}`); w.Code != 400 {
		t.Fatal(w.Code)
	}
	if err := a.setRecording(true); err != nil {
		t.Fatal(err)
	}
	if w := request(t, a, "POST", "/api/exposure", `{"mode":"manual","value":300}`); w.Code != 409 {
		t.Fatal("recording allowed setting", w.Code)
	}
	a.recordMu.Lock()
	file := filepath.Join(a.recorder.path, "session.json")
	a.recordMu.Unlock()
	data, _ := os.ReadFile(file)
	var meta struct {
		Exposure ExposureSettings `json:"exposure"`
	}
	json.Unmarshal(data, &meta)
	if meta.Exposure != defaultExposure() {
		t.Fatal("exposure metadata missing", meta)
	}
	a.setRecording(false)
	if err := a.drive(DriveRequest{Client: "exposure-test", Sequence: 1, Gesture: 1, Enable: true}); err != nil {
		t.Fatal(err)
	}
	if w := request(t, a, "POST", "/api/exposure", `{"mode":"manual","value":300}`); w.Code != 409 {
		t.Fatal("active drive accepted setting", w.Code)
	}
}

type controlledExposure struct {
	*Simulator
	entered chan struct{}
	resume  chan struct{}
	err     error
}

func (b *controlledExposure) ApplyExposure(ctx context.Context, s ExposureSettings) error {
	close(b.entered)
	select {
	case <-b.resume:
	case <-ctx.Done():
		return ctx.Err()
	}
	if b.err != nil {
		return b.err
	}
	return b.Simulator.ApplyExposure(ctx, s)
}
func TestExposureBusyBlocksDriveRecordingAndConcurrentChanges(t *testing.T) {
	b := &controlledExposure{Simulator: newSimulator(), entered: make(chan struct{}), resume: make(chan struct{})}
	a := &App{backend: b, dataRoot: t.TempDir(), maxThrottle: 1, exposurePath: filepath.Join(t.TempDir(), "exposure.json")}
	ctx, cancel := context.WithCancel(context.Background())
	a.start(ctx)
	defer func() { cancel(); a.wg.Wait(); b.Close() }()
	until(t, func() bool { a.mu.Lock(); defer a.mu.Unlock(); return !a.lastFrame.IsZero() })
	done := make(chan error, 1)
	go func() { done <- a.setExposure(ExposureSettings{"manual", 200}) }()
	<-b.entered
	if err := a.drive(DriveRequest{Client: "exposure-test", Sequence: 1, Gesture: 1, Enable: true}); err == nil {
		t.Fatal("busy camera allowed drive")
	}
	if a.setRecording(true) == nil {
		t.Fatal("busy camera allowed recording")
	}
	if a.setExposure(defaultExposure()) == nil {
		t.Fatal("concurrent exposure accepted")
	}
	if !a.status()["exposure"].(map[string]any)["busy"].(bool) {
		t.Fatal("missing busy status")
	}
	close(b.resume)
	if err := <-done; err != nil {
		t.Fatal(err)
	}
}
func TestExposureHardwareFailureIsNotSavedAndLocksDrive(t *testing.T) {
	b := &controlledExposure{Simulator: newSimulator(), entered: make(chan struct{}), resume: make(chan struct{}), err: errors.New("SCCB readback mismatch")}
	close(b.resume)
	defer b.Close()
	path := filepath.Join(t.TempDir(), "exposure.json")
	a := &App{backend: b, maxThrottle: 1, exposurePath: path, lastFrame: time.Now()}
	if a.setExposure(ExposureSettings{"manual", 300}) == nil {
		t.Fatal("hardware failure ignored")
	}
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Fatal("unconfirmed setting saved")
	}
	if a.fault == "" || a.exposureBusy {
		t.Fatal("failed setting not locked", a.fault)
	}
}
func TestExposurePersistenceFailureDoesNotTouchHardware(t *testing.T) {
	b := &controlledExposure{Simulator: newSimulator(), entered: make(chan struct{}), resume: make(chan struct{})}
	defer b.Close()
	a := &App{backend: b, maxThrottle: 1, lastFrame: time.Now(), exposurePath: ""}
	if a.setExposure(defaultExposure()) == nil {
		t.Fatal("missing persistent path accepted")
	}
	select {
	case <-b.entered:
		t.Fatal("hardware touched before persistence prepared")
	default:
	}
	if a.exposureBusy || a.fault != "" {
		t.Fatal("file preparation failure left camera locked")
	}
}
