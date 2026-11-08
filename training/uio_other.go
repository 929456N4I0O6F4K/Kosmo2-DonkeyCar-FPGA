//go:build !linux

package main

import "errors"

func openUIO(device string) (Backend, error) {
	return nil, errors.New("UIO requires Linux; use -backend sim on this computer")
}
