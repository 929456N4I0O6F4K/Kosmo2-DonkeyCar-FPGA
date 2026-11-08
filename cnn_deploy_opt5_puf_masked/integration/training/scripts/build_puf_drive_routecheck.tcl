set root [file normalize [file join [file dirname [info script]] ..]]
set output [file normalize [pwd]]
if {[string tolower [file normalize [file dirname $output]]] ne [string tolower [file normalize [file join $root build board]]] ||
    ![string match ro_capture_* [file tail $output]]} {
 error "Run this route-check build from a fresh integration/training/build/board/ro_capture_* directory."
}
cd $output
set_option max_threads 1
set key_mode 1d0e0
set finish_marker PUF_DRIVE_ROUTECHECK_BUILD_FINISHED
set_arch -family Kosmo2 -device PG2K100 -speedgrade -6 -package MBG400
set generated_data_dir [file join $output model_snapshot]
source [file join $root scripts build_common.tcl]
synthesize -ads -selected_syn_tool_opt 2
finish_build $output $finish_marker
