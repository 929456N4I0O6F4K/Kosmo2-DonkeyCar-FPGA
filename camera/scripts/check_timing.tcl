# Gate programming-file generation on post-route timing.
proc check_camera_timing {path} {
 set handle [open $path r]
 set report [read $handle]
 close $handle
 if {![regexp {Design Summary\s*:\s*All Constraints Met\.} $report]} {
  error "Camera timing failed: $path"
 }
 if {![regexp {sysclk_50\s+20\.0000} $report] || ![regexp {cam_pclk\s+41\.6670} $report]} {
  error "Expected 50 MHz system / 24 MHz PCLK constraints are missing: $path"
 }
 puts "CAMERA_TIMING_PASS: $path"
}

