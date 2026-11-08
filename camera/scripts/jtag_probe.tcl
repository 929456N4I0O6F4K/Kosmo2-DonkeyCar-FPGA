dbg_connect -ip 127.0.0.1 -port 65420
dbg_scan_chain
dbg_dvio_print -device 1 -dvio 0
dbg_dvio_refresh_input -device 1 -dvio 0
dbg_dvio_print -device 1 -dvio 0
dbg_disconnect
dbg_close
