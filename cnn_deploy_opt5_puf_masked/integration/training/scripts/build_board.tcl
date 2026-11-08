set root [file normalize [file join [file dirname [info script]] ..]]
set output [file join $root build board]
file mkdir $output
if {[string tolower [file normalize [pwd]]] ne [string tolower $output]} {
 error "Start PDS from $output; PDS creates tasks in its launch directory before this script runs."
}
cd $output
set_option max_threads 1
# The production key is written by tools/configure_puf_reference.py from a board-A
# capture of the ro_capture_* image built from these same sources.
set key_mode 1d0e0
set finish_marker TRAINING_BOARD_BUILD_FINISHED
set_arch -family Kosmo2 -device PG2K100 -speedgrade -6 -package MBG400
source [file join $root scripts build_common.tcl]
synthesize -ads -selected_syn_tool_opt 2
finish_build $output $finish_marker
