package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
)

// Percentages refer to the original independently calibrated left/right spans.
type SteeringSettings struct {
	LeftPercent  int `json:"left_percent"`
	RightPercent int `json:"right_percent"`
}

func defaultSteering() SteeringSettings { return SteeringSettings{110, 110} }
func (s SteeringSettings) resolved() SteeringSettings {
	if s == (SteeringSettings{}) {
		return defaultSteering()
	}
	return s
}
func (s SteeringSettings) validate() error {
	if s.LeftPercent < 50 || s.LeftPercent > 150 || s.RightPercent < 50 || s.RightPercent > 150 {
		return errors.New("左右转向幅度必须是 50～150 的整数百分比")
	}
	return nil
}
func (s SteeringSettings) ticks() (int, int) {
	s = s.resolved()
	return 428 + (67*s.LeftPercent+50)/100, 428 - (63*s.RightPercent+50)/100
}
func (s SteeringSettings) packed() uint32 {
	left, right := s.ticks()
	return uint32(left) | uint32(right)<<16
}
func (s SteeringSettings) info() map[string]any {
	s = s.resolved()
	left, right := s.ticks()
	return map[string]any{"left_percent": s.LeftPercent, "right_percent": s.RightPercent,
		"left_ticks": left, "center_ticks": 428, "right_ticks": right, "min_percent": 50, "max_percent": 150}
}
func loadSteering(path string) (SteeringSettings, error) {
	data, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return defaultSteering(), nil
	}
	if err != nil {
		return SteeringSettings{}, err
	}
	var s SteeringSettings
	d := json.NewDecoder(bytes.NewReader(data))
	d.DisallowUnknownFields()
	if err = d.Decode(&s); err != nil {
		return s, err
	}
	var extra any
	if d.Decode(&extra) != io.EOF {
		return s, errors.New("trailing steering settings JSON")
	}
	return s, s.validate()
}
func saveSteering(path string, s SteeringSettings) error {
	if err := s.validate(); err != nil {
		return err
	}
	if path == "" {
		return errors.New("steering settings path is not configured")
	}
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return err
	}
	f, err := os.CreateTemp(filepath.Dir(path), ".steering-*.tmp")
	if err != nil {
		return err
	}
	defer os.Remove(f.Name())
	if err = json.NewEncoder(f).Encode(s); err == nil {
		err = f.Sync()
	}
	closeErr := f.Close()
	if err == nil {
		err = closeErr
	}
	if err != nil {
		return err
	}
	return os.Rename(f.Name(), path)
}
func (a *App) setSteering(s SteeringSettings) error {
	if err := s.validate(); err != nil {
		return err
	}
	// Same lock order as recording/status; a recording's calibration is immutable.
	a.recordMu.Lock()
	defer a.recordMu.Unlock()
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.exposureBusy || a.recordOpening || a.desired.Enable || a.latest.Flags&enabledFlag != 0 || a.recorder != nil {
		return errors.New("请先停车并结束录制，再保存转向设置")
	}
	if err := saveSteering(a.steeringPath, s); err != nil {
		return fmt.Errorf("保存转向设置失败: %w", err)
	}
	a.steering = s
	return nil
}
