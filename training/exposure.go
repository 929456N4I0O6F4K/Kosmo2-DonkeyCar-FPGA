package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"time"
)

// Value is the sensor's integration setting, not calibrated microseconds.
type ExposureSettings struct {
	Mode  string `json:"mode"`
	Value int    `json:"value"`
}

func defaultExposure() ExposureSettings { return ExposureSettings{"auto", 300} }
func (s ExposureSettings) resolved() ExposureSettings {
	if s == (ExposureSettings{}) {
		return defaultExposure()
	}
	return s
}
func (s ExposureSettings) validate() error {
	if (s.Mode != "auto" && s.Mode != "manual") || s.Value < 0 || s.Value > 1200 {
		return errors.New("曝光模式须为 auto 或 manual，曝光值须为 0～1200 的整数")
	}
	return nil
}
func (s ExposureSettings) packed() uint32 {
	v := uint32(s.Value)
	if s.Mode == "auto" {
		v |= 1 << 31
	}
	return v
}

type exposureBackend interface {
	ApplyExposure(context.Context, ExposureSettings) error
}

func supportsExposure(b Backend) bool {
	if capability, ok := b.(interface{ ExposureSupported() bool }); ok {
		return capability.ExposureSupported()
	}
	_, ok := b.(exposureBackend)
	return ok
}

func loadExposure(path string) (ExposureSettings, error) {
	data, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return defaultExposure(), nil
	}
	if err != nil {
		return ExposureSettings{}, err
	}
	var s ExposureSettings
	d := json.NewDecoder(bytes.NewReader(data))
	d.DisallowUnknownFields()
	if err = d.Decode(&s); err != nil {
		return s, err
	}
	var extra any
	if d.Decode(&extra) != io.EOF {
		return s, errors.New("trailing exposure settings JSON")
	}
	return s, s.validate()
}

// Prepare durable contents before touching hardware. Commit is an atomic rename.
func stageExposure(path string, s ExposureSettings) (func() error, func(), error) {
	if err := s.validate(); err != nil {
		return nil, nil, err
	}
	if path == "" {
		return nil, nil, errors.New("exposure settings path is not configured")
	}
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return nil, nil, err
	}
	f, err := os.CreateTemp(filepath.Dir(path), ".exposure-*.tmp")
	if err != nil {
		return nil, nil, err
	}
	cleanup := func() { os.Remove(f.Name()) }
	err = json.NewEncoder(f).Encode(s)
	if err == nil {
		err = f.Sync()
	}
	closeErr := f.Close()
	if err == nil {
		err = closeErr
	}
	if err != nil {
		cleanup()
		return nil, nil, err
	}
	return func() error { return os.Rename(f.Name(), path) }, cleanup, nil
}
func (s *Simulator) ApplyExposure(ctx context.Context, e ExposureSettings) error {
	if err := e.validate(); err != nil {
		return err
	}
	if err := ctx.Err(); err != nil {
		return err
	}
	s.mu.Lock()
	s.exposure = e
	s.mu.Unlock()
	return nil
}
func (a *App) exposureInfo() map[string]any {
	e := a.exposure.resolved()
	supported := supportsExposure(a.backend)
	return map[string]any{"mode": e.Mode, "value": e.Value, "min": 0, "max": 1200,
		"busy": a.exposureBusy, "supported": supported, "manual_gain": "hold at mode switch"}
}
func (a *App) setExposure(s ExposureSettings) error {
	if err := s.validate(); err != nil {
		return err
	}
	b, ok := a.backend.(exposureBackend)
	if !ok || !supportsExposure(a.backend) {
		return errors.New("当前固件不支持曝光调节，请完整部署新版固件")
	}
	a.recordMu.Lock()
	a.mu.Lock()
	if a.exposureBusy || a.recordOpening || a.desired.Enable || a.latest.Flags != 0 || a.recorder != nil || a.fault != "" || time.Since(a.lastFrame) >= 500*time.Millisecond {
		a.mu.Unlock()
		a.recordMu.Unlock()
		return errors.New("请先停车、结束录制，并等待正常视频后再调整曝光")
	}
	old := a.exposure.resolved()
	a.exposureBusy = true
	a.mu.Unlock()
	a.recordMu.Unlock()
	defer func() { a.mu.Lock(); a.exposureBusy = false; a.mu.Unlock() }()
	commit, cleanup, err := stageExposure(a.exposurePath, s)
	if err != nil {
		return fmt.Errorf("无法保存曝光配置，未修改相机: %w", err)
	}
	defer cleanup()
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	if err = b.ApplyExposure(ctx, s); err != nil {
		a.fail(fmt.Errorf("曝光设置未确认，请重新启动采集服务: %w", err))
		return err
	}
	// Drain frames captured during register writes before allowing recording/drive.
	a.mu.Lock()
	first := a.frameCount
	a.mu.Unlock()
	tick := time.NewTicker(10 * time.Millisecond)
	defer tick.Stop()
	for {
		a.mu.Lock()
		fresh := a.frameCount >= first+3 && time.Since(a.lastFrame) < 500*time.Millisecond
		fault := a.fault
		a.mu.Unlock()
		if fault != "" {
			return errors.New(fault)
		}
		if fresh {
			break
		}
		select {
		case <-ctx.Done():
			a.fail(errors.New("曝光切换后视频未恢复，请重新启动采集服务"))
			return ctx.Err()
		case <-tick.C:
		}
	}
	if err = commit(); err != nil {
		restoreCtx, restoreCancel := context.WithTimeout(context.Background(), time.Second)
		restoreErr := b.ApplyExposure(restoreCtx, old)
		restoreCancel()
		// A failed commit or rollback requires restart; no mislabeled recording.
		a.fail(fmt.Errorf("曝光配置保存失败，请重新启动采集服务: %v (restore: %v)", err, restoreErr))
		return err
	}
	a.mu.Lock()
	a.exposure = s
	a.mu.Unlock()
	return nil
}
