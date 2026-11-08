package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestSteeringRangePackingAndPersistence(t *testing.T) {
	for _, tc := range []struct {
		s           SteeringSettings
		left, right int
	}{
		{SteeringSettings{100, 100}, 495, 365}, {defaultSteering(), 502, 359},
		{SteeringSettings{150, 50}, 529, 396}, {SteeringSettings{50, 150}, 462, 333},
	} {
		left, right := tc.s.ticks()
		if left != tc.left || right != tc.right || tc.s.packed() != uint32(left)|uint32(right)<<16 {
			t.Fatal(tc, left, right)
		}
	}
	path := filepath.Join(t.TempDir(), "steering.json")
	if s, err := loadSteering(path); err != nil || s != defaultSteering() {
		t.Fatal(s, err)
	}
	for _, s := range []SteeringSettings{{125, 90}, {80, 140}} {
		if err := saveSteering(path, s); err != nil {
			t.Fatal(err)
		}
		if loaded, err := loadSteering(path); err != nil || loaded != s {
			t.Fatal(loaded, err)
		}
	}
	if err := saveSteering(path, SteeringSettings{151, 100}); err == nil {
		t.Fatal("unsafe range persisted")
	}
	if s, _ := loadSteering(path); s != (SteeringSettings{80, 140}) {
		t.Fatal("failed update changed saved settings")
	}
	for _, text := range []string{`{}`, `{"left_percent":0,"right_percent":110}`, `{"left_percent":110,"right_percent":110} {}`, `{"left_percent":110,"right_percent":110,"extra":1}`} {
		if err := os.WriteFile(path, []byte(text), 0600); err != nil {
			t.Fatal(err)
		}
		if _, err := loadSteering(path); err == nil {
			t.Fatal("invalid persisted settings accepted", text)
		}
	}
}

func TestSteeringAPIIdleOnlyAndRecordingMetadata(t *testing.T) {
	a := testApp(t)
	a.mu.Lock()
	a.steeringPath = filepath.Join(t.TempDir(), "steering.json")
	a.mu.Unlock()
	post := func(body string, code int) {
		t.Helper()
		r := request(t, a, "POST", "/api/steering", body)
		if r.Code != code {
			t.Fatalf("status %d: %s", r.Code, r.Body.String())
		}
	}
	post(`{"left_percent":125,"right_percent":90}`, 200)
	b := a.backend.(*Simulator)
	until(t, func() bool { b.mu.Lock(); defer b.mu.Unlock(); return b.cmd.Steering == (SteeringSettings{125, 90}) })
	a.mu.Lock()
	if a.desired.Enable {
		t.Fatal("saving steering enabled drive")
	}
	a.mu.Unlock()
	post(`{"left_percent":151,"right_percent":90}`, 400)
	post(`{"left_percent":110.5,"right_percent":90}`, 400)
	r := DriveRequest{Client: "steering-test", Sequence: 1, Gesture: 1, Enable: true, Angle: -1}
	if err := a.drive(r); err != nil {
		t.Fatal(err)
	}
	post(`{"left_percent":100,"right_percent":100}`, 409)
	until(t, func() bool { a.mu.Lock(); defer a.mu.Unlock(); return a.latest.Angle == -1 })
	r.Enable = false
	r.Sequence++
	if err := a.drive(r); err != nil {
		t.Fatal(err)
	}
	until(t, func() bool { a.mu.Lock(); defer a.mu.Unlock(); return a.latest.Flags == 0 })
	if err := a.setRecording(true); err != nil {
		t.Fatal(err)
	}
	post(`{"left_percent":100,"right_percent":100}`, 409)
	a.recordMu.Lock()
	metadataPath := filepath.Join(a.recorder.path, "session.json")
	a.recordMu.Unlock()
	data, err := os.ReadFile(metadataPath)
	if err != nil {
		t.Fatal(err)
	}
	var metadata struct {
		Steering SteeringSettings `json:"steering"`
	}
	if err := json.Unmarshal(data, &metadata); err != nil {
		t.Fatal(err)
	}
	if metadata.Steering != (SteeringSettings{125, 90}) {
		t.Fatal("recording calibration missing", metadata)
	}
	if err := a.setRecording(false); err != nil {
		t.Fatal(err)
	}
	post(`{"left_percent":100,"right_percent":100}`, 200)
	if saved, err := loadSteering(a.steeringPath); err != nil || saved != (SteeringSettings{100, 100}) {
		t.Fatal(saved, err)
	}
}

func TestSteeringSaveFailureAndPendingStopDoNotChangeSettings(t *testing.T) {
	root := t.TempDir()
	file := filepath.Join(root, "not-a-directory")
	if err := os.WriteFile(file, []byte("x"), 0600); err != nil {
		t.Fatal(err)
	}
	a := &App{steering: defaultSteering(), steeringPath: filepath.Join(file, "steering.json"), lastFrame: time.Now()}
	if err := a.setSteering(SteeringSettings{120, 120}); err == nil {
		t.Fatal("failed write accepted")
	}
	if a.steering != defaultSteering() {
		t.Fatal("in-memory calibration changed before persistence")
	}
	a.steeringPath = filepath.Join(root, "settings.json")
	a.latest.Flags = enabledFlag // accepted old drive frame still in flight after stop request
	if err := a.setSteering(SteeringSettings{120, 120}); err == nil {
		t.Fatal("pending physical command accepted settings")
	}
	if _, err := os.Stat(a.steeringPath); !os.IsNotExist(err) {
		t.Fatal("busy request touched file")
	}
}
