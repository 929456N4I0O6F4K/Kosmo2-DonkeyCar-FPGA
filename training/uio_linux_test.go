//go:build linux

package main

import (
	"context"
	"strings"
	"testing"
	"time"
)

// Simulate PA publication in ordinary memory; never opens /dev/uio or MMIO.
func TestExposureMailboxConfirmation(t *testing.T) {
	for _, test := range []struct {
		name            string
		status          uint32
		mismatch, reset bool
		want            string
	}{
		{"confirmed", 1, false, false, ""},
		{"SCCB failure", 3, false, false, "3"},
		{"wrong applied value", 1, true, false, "回执"},
		{"transport reset", 1, false, true, "reset"},
	} {
		t.Run(test.name, func(t *testing.T) {
			u := &UIO{mem: make([]byte, mapBytes), exposureSeq: 41, seq: 19}
			u.put(0, abiMagic)
			u.put(4, abiVersion)
			// An older success ACK must not confirm this request.
			u.put(0x88, 41)
			u.put(0x8c, 1)
			u.put(0x90, 300)
			ctx, cancel := context.WithTimeout(context.Background(), time.Second)
			defer cancel()
			done := make(chan error, 1)
			go func() { done <- u.ApplyExposure(ctx, ExposureSettings{"manual", 300}) }()
			until(t, func() bool { return u.get(0x80) == 42 })
			select {
			case err := <-done:
				t.Fatal("stale ACK accepted", err)
			default:
			}
			if u.get(0x84) != 300 || u.seq != 19 {
				t.Fatal("payload or control sequence changed")
			}
			if test.reset {
				u.put(4, 2)
			} else {
				applied := uint32(300)
				if test.mismatch {
					applied++
				}
				u.put(0x8c, test.status)
				u.put(0x90, applied)
				u.put(0x88, 42)
			}
			err := <-done
			if test.want == "" {
				if err != nil {
					t.Fatal(err)
				}
			} else if err == nil || !strings.Contains(err.Error(), test.want) {
				t.Fatal(err)
			}
		})
	}
}

func TestExposureMailboxTimeoutAndSequenceWrap(t *testing.T) {
	u := &UIO{mem: make([]byte, mapBytes), exposureSeq: ^uint32(0)}
	u.put(0, abiMagic)
	u.put(4, abiVersion)
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Millisecond)
	defer cancel()
	if err := u.ApplyExposure(ctx, defaultExposure()); err != context.DeadlineExceeded {
		t.Fatal(err)
	}
	if u.get(0x80) != 1 || u.get(0x84) != 0x8000012c {
		t.Fatal("zero sequence or wrong auto setting")
	}
}

func TestLegacyTransportRunsControlButNeverWritesExposure(t *testing.T) {
	u := &UIO{mem: make([]byte, mapBytes), abi: 2}
	u.put(0, abiMagic)
	u.put(4, 2)
	if supportsExposure(u) {
		t.Fatal("legacy FPGA advertised exposure")
	}
	if err := u.ApplyExposure(context.Background(), defaultExposure()); err == nil {
		t.Fatal("legacy exposure accepted")
	}
	if u.get(0x80) != 0 || u.get(0x84) != 0 {
		t.Fatal("unsupported mailbox written")
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	done := make(chan error, 1)
	go func() { _, err := u.Apply(ctx, Command{}); done <- err }()
	until(t, func() bool { return u.get(0x10) != 0 })
	u.put(0x28, 1)
	u.put(0x24, u.get(0x10))
	if err := <-done; err != nil {
		t.Fatal("ABI 2 control rejected", err)
	}
}
