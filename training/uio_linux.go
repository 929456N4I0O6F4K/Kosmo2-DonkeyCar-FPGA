//go:build linux

package main

import (
	"context"
	"errors"
	"fmt"
	"os"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"time"
	"unsafe"
)

const abiMagic = uint32(0x3152544b) // KTR1, little endian
const abiVersion = uint32(3)        // independent exposure mailbox at 0x80
const mapBytes = 0x10000

type UIO struct {
	mem         []byte
	fd          *os.File
	seq         uint32
	abi         uint32
	exposureMu  sync.Mutex
	exposureSeq uint32
}

func openUIO(device string) (Backend, error) {
	// Do not map an arbitrary UIO device or guess an MMIO register address.
	name := strings.TrimPrefix(device, "/dev/")
	if strings.Contains(name, "/") || !strings.HasPrefix(name, "uio") {
		return nil, errors.New("expected /dev/uioN")
	}
	root := "/sys/class/uio/" + name
	n, err := os.ReadFile(root + "/name")
	if err != nil {
		return nil, err
	}
	if strings.TrimSpace(string(n)) != "pu-pa-ddr" {
		return nil, errors.New("UIO is not pu-pa-ddr")
	}
	for _, item := range []struct {
		path  string
		value uint64
	}{{"addr", 0x00300000}, {"size", 0x04000000}, {"offset", 0}} {
		data, e := os.ReadFile(root + "/maps/map0/" + item.path)
		if e != nil {
			return nil, e
		}
		v, e := strconv.ParseUint(strings.TrimSpace(string(data)), 0, 64)
		if e != nil || v != item.value {
			return nil, fmt.Errorf("unexpected UIO %s", item.path)
		}
	}
	fd, err := os.OpenFile(device, os.O_RDWR|syscall.O_SYNC, 0)
	if err != nil {
		return nil, err
	}
	if err = syscall.Flock(int(fd.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		fd.Close()
		return nil, fmt.Errorf("UIO already in use: %w", err)
	}
	mem, err := syscall.Mmap(int(fd.Fd()), 0, mapBytes, syscall.PROT_READ|syscall.PROT_WRITE, syscall.MAP_SHARED)
	if err != nil {
		fd.Close()
		return nil, err
	}
	u := &UIO{mem: mem, fd: fd}
	u.abi = u.get(4)
	if u.get(0) != abiMagic || (u.abi != 2 && u.abi != abiVersion) {
		u.Close()
		return nil, errors.New("PA KTR1 ABI 2 or 3 required; exposure needs ABI 3 firmware")
	}
	u.seq = u.get(0x10)
	u.exposureSeq = u.get(0x80)
	// Discard the slot from a previous daemon before starting a new session.
	u.put(0x2c, u.get(0x30))
	return u, nil
}

// Acquire/release loads/stores on aligned uncached shared DDR. PA must finish
// all AXI write responses before publishing; it must not reuse an owned slot.
func (u *UIO) get(off int) uint32    { return atomic.LoadUint32((*uint32)(unsafe.Pointer(&u.mem[off]))) }
func (u *UIO) put(off int, v uint32) { atomic.StoreUint32((*uint32)(unsafe.Pointer(&u.mem[off])), v) }
func (u *UIO) Name() string          { return "pa-uio-ktr1" }
func (u *UIO) transportABI() uint32 {
	if u.abi == 0 {
		return abiVersion
	}
	return u.abi
}
func (u *UIO) ExposureSupported() bool { return u.transportABI() == abiVersion }
func (u *UIO) ApplyExposure(ctx context.Context, s ExposureSettings) error {
	if !u.ExposureSupported() {
		return errors.New("exposure requires FPGA ABI 3; run full deployment")
	}
	if err := s.validate(); err != nil {
		return err
	}
	u.exposureMu.Lock()
	defer u.exposureMu.Unlock()
	u.exposureSeq++
	if u.exposureSeq == 0 {
		u.exposureSeq++
	}
	u.put(0x80, 0)
	u.put(0x84, s.packed())
	u.put(0x80, u.exposureSeq)
	tick := time.NewTicker(time.Millisecond)
	defer tick.Stop()
	for {
		if u.get(0) != abiMagic || u.get(4) != u.transportABI() {
			return errors.New("PA exposure transport reset")
		}
		if u.get(0x88) == u.exposureSeq {
			if u.get(0x8c) != 1 {
				return fmt.Errorf("相机曝光设置失败，硬件状态 %d", u.get(0x8c))
			}
			if u.get(0x90) != s.packed() {
				return errors.New("相机曝光配置回执不匹配")
			}
			return nil
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-tick.C:
		}
	}
}
func (u *UIO) Health() map[string]bool {
	v := u.get(0x34)
	return map[string]bool{"ready": v&1 != 0, "fault": v&2 != 0, "active": v&4 != 0, "armed": v&8 != 0, "shutdown_unconfirmed": v&16 != 0, "stop": v&32 != 0}
}
func (u *UIO) Apply(ctx context.Context, c Command) (uint32, error) {
	if !validCommand(c) {
		return 0, errors.New("invalid command")
	}
	u.seq++
	if u.seq == 0 {
		u.seq++
	}
	// Invalidate before changing payload, including after an ACK timeout.
	// PA checks the sequence both before and after its payload reads.
	u.put(0x10, 0)
	u.put(0x14, c.Flags)
	u.put(0x18, uint32(int32(c.Angle*1e6)))
	u.put(0x1c, uint32(int32(c.Throttle*1e6)))
	u.put(0x20, 300)
	u.put(0x38, c.Steering.packed())
	u.put(0x10, u.seq)
	tick := time.NewTicker(time.Millisecond)
	defer tick.Stop()
	for {
		if u.get(0) != abiMagic || u.get(4) != u.transportABI() {
			return 0, errors.New("PA transport reset")
		}
		if u.get(0x24) == u.seq {
			if u.get(0x28) != 1 {
				return 0, errors.New("PA control rejected command")
			}
			return u.seq, nil
		}
		select {
		case <-ctx.Done():
			return 0, ctx.Err()
		case <-tick.C:
		}
	}
}
func (u *UIO) Next(ctx context.Context) (Frame, error) {
	tick := time.NewTicker(time.Millisecond)
	defer tick.Stop()
	for {
		if u.get(0) != abiMagic || u.get(4) != u.transportABI() {
			return Frame{}, errors.New("PA transport unavailable")
		}
		seq := u.get(0x30)
		if seq != u.get(0x2c) {
			if u.get(0x40) != seq || u.get(0x44) != width*height*2 {
				return Frame{}, errors.New("bad PA frame descriptor")
			}
			f := Frame{Sequence: seq, CaptureUS: (uint64(u.get(0x4c))<<32 | uint64(u.get(0x48))) / 50, CommandSequence: u.get(0x50), Angle: float64(int32(u.get(0x54))) / 1e6, Throttle: float64(int32(u.get(0x58))) / 1e6, Flags: u.get(0x5c), Dropped: u.get(0x60), RGB: make([]byte, width*height*3)}
			// Use aligned word reads for the device mapping. Sensor bytes are MSB first.
			for i := 0; i < width*height; i += 2 {
				word := u.get(0x1000 + i*2)
				for j := 0; j < 2; j++ {
					p := uint16((word>>uint(j*16))&255)<<8 | uint16((word>>uint(j*16+8))&255)
					r, g, b := byte(p>>11), byte((p>>5)&63), byte(p&31)
					pos := (i + j) * 3
					f.RGB[pos] = (r << 3) | (r >> 2)
					f.RGB[pos+1] = (g << 2) | (g >> 4)
					f.RGB[pos+2] = (b << 3) | (b >> 2)
				}
			}
			if u.get(0x30) != seq {
				return Frame{}, errors.New("PA overwrote a frame still owned by PU")
			}
			u.put(0x2c, seq)
			return f, f.Validate()
		}
		select {
		case <-ctx.Done():
			return Frame{}, ctx.Err()
		case <-tick.C:
		}
	}
}
func (u *UIO) Close() error {
	err := syscall.Munmap(u.mem)
	e := u.fd.Close()
	if err != nil {
		return err
	}
	return e
}
