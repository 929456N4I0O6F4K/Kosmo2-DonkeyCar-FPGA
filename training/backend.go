package main

import (
	"context"
	"errors"
	"image"
	"image/color"
	"math"
	"sync"
	"time"
)

const width, height = 160, 120
const enabledFlag, recordFlag = uint32(1), uint32(2)

// Labels describe the command accepted by the control core at frame start.
// They are requested actuator setpoints, not measured wheel angle or speed.
type Frame struct {
	Sequence        uint32    `json:"frame_sequence"`
	CaptureUS       uint64    `json:"capture_us"`
	CommandSequence uint32    `json:"command_sequence"`
	Angle           float64   `json:"user/angle"`
	Throttle        float64   `json:"user/throttle"`
	Flags           uint32    `json:"flags"`
	Dropped         uint32    `json:"source_dropped"`
	RGB             []byte    `json:"-"`
	ReceivedUTC     time.Time `json:"-"`
}
type Command struct {
	Angle, Throttle float64
	Flags           uint32
	Steering        SteeringSettings
}
type Backend interface {
	Next(context.Context) (Frame, error)
	Apply(context.Context, Command) (uint32, error)
	Close() error
	Name() string
}

func validCommand(c Command) bool {
	return !math.IsNaN(c.Angle) && !math.IsInf(c.Angle, 0) &&
		!math.IsNaN(c.Throttle) && !math.IsInf(c.Throttle, 0) &&
		c.Angle >= -1 && c.Angle <= 1 && c.Throttle >= 0 && c.Throttle <= 1 && c.Flags & ^uint32(3) == 0 && c.Steering.resolved().validate() == nil
}
func (f Frame) Validate() error {
	if len(f.RGB) != width*height*3 || !validCommand(Command{Angle: f.Angle, Throttle: f.Throttle, Flags: f.Flags}) {
		return errors.New("invalid frame size or labels")
	}
	if f.Flags&recordFlag != 0 && f.Flags&enabledFlag == 0 {
		return errors.New("recorded frame without enabled control")
	}
	return nil
}
func (f Frame) Image() *image.RGBA {
	im := image.NewRGBA(image.Rect(0, 0, width, height))
	for p := 0; p < width*height; p++ {
		copy(im.Pix[p*4:p*4+3], f.RGB[p*3:p*3+3])
		im.Pix[p*4+3] = 255
	}
	return im
}

type Simulator struct {
	mu                   sync.Mutex
	started              time.Time
	lastApply            time.Time
	cmd                  Command
	exposure             ExposureSettings
	commandSeq, frameSeq uint32
	ticker               *time.Ticker
}

func newSimulator() *Simulator {
	return &Simulator{started: time.Now(), ticker: time.NewTicker(time.Second / 15)}
}
func (s *Simulator) Name() string { return "simulation" }
func (s *Simulator) Apply(ctx context.Context, c Command) (uint32, error) {
	if !validCommand(c) {
		return 0, errors.New("invalid command")
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	s.commandSeq++
	s.cmd = c
	s.lastApply = time.Now()
	return s.commandSeq, nil
}
func (s *Simulator) Next(ctx context.Context) (Frame, error) {
	select {
	case <-ctx.Done():
		return Frame{}, ctx.Err()
	case <-s.ticker.C:
	}
	s.mu.Lock()
	c := s.cmd
	if time.Since(s.lastApply) > 300*time.Millisecond {
		c = Command{}
	}
	s.frameSeq++
	f := Frame{Sequence: s.frameSeq, CaptureUS: uint64(time.Since(s.started).Microseconds()), CommandSequence: s.commandSeq, Angle: c.Angle, Throttle: c.Throttle, Flags: c.Flags, RGB: make([]byte, width*height*3)}
	s.mu.Unlock()
	for y := 0; y < height; y++ {
		for x := 0; x < width; x++ {
			col := color.RGBA{70, 145, 185, 255}
			if y > 40 {
				center := 80 + int(c.Angle*float64(y-40)*.4)
				if abs(x-center) < (y-35)/2 {
					col = color.RGBA{70, 75, 80, 255}
				} else {
					col = color.RGBA{45, 105, 60, 255}
				}
				if abs(x-center) < 2 && (y+int(f.Sequence))%20 < 12 {
					col = color.RGBA{240, 220, 140, 255}
				}
			}
			p := (y*width + x) * 3
			f.RGB[p] = col.R
			f.RGB[p+1] = col.G
			f.RGB[p+2] = col.B
		}
	}
	return f, nil
}
func abs(v int) int {
	if v < 0 {
		return -v
	}
	return v
}
func (s *Simulator) Close() error { s.ticker.Stop(); return nil }
