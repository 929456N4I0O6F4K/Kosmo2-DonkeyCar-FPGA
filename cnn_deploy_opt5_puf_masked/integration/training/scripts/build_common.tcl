# Shared by build_puf_capture.tcl (capture key) and build_board.tcl (production
# key). Both images must come from identical sources, order, options and
# constraints, so that the capture image is the same physical implementation
# that runs with the enrolled binding. The only permitted difference is the
# block-ROM content of $output/puf_key.mem.
# Caller sets: root, output, key_mode (5-digit hex mode word), finish_marker.
# pds_shell picks the project type from the entry script's own top-level
# set_arch and "synthesize -ads" lines, not from sourced files, so the caller
# runs those two commands itself and calls finish_build after synthesize.
set key_file [file join $output puf_key.mem]
if {![file exists $key_file]} {
 error "Write $key_file first (tools/puf_key_image.py capture, or tools/configure_puf_reference.py)."
}
set f [open $key_file r]
set key_words [split [string trim [read $f]] "\n"]
close $f
if {[llength $key_words] != 32 || [string tolower [string trim [lindex $key_words 16]]] ne $key_mode} {
 error "$key_file is not a $key_mode-mode key image."
}
set cnn [file normalize [file join $root .. .. rtl]]
if {![info exists generated_data_dir]} {
 set generated_data_dir [file join $cnn generated]
}
foreach stray [list [file join $cnn puf_key.mem] [file join $cnn generated puf_key.mem]] {
 if {[file exists $stray]} {error "Remove $stray; the key ROM must come only from the build directory."}
}
# A local copy makes $readmemh resolve puf_key.mem in this directory.
file copy -force [file join $cnn puf_key_store.v] [file join $output puf_key_store.v]

foreach path [glob [file join $root rtl *.v] [file join $root board *.v] [file join $root board vendor *.v]] { add_design $path }
foreach name {camera_capture camera_config camera_sccb camera_exposure ov2640_init_rom} {add_design [file join $root .. camera rtl $name.v]}
foreach name {pca_i2c pca_dvio} {add_design [file join $root .. actuators rtl $name.v]}
set iproot C:/pango/PDS_2025.2-ads/ip/system_ip/ips_dvio/ips_dvio_eval
foreach path [glob [file join $iproot ips_dvio rtl *.v] [file join $iproot ips_dvio_jtag_hub rtl *.v]] {add_design $path}
foreach name {camera_cnn_pipeline rgb565_crop mypilot_cnn_core mypilot_layer_engine mypilot_banked_ram mypilot_requantize ro_puf_enroll} {add_design [file join $cnn $name.v]}
add_design [file join $output puf_key_store.v]
set puf [file normalize [file join $root .. .. .. ro_puf rtl]]
foreach name {ro_cell ro_bank ro_counter} {add_design [file join $puf $name.v]}
set parameters_file [file join $generated_data_dir mypilot_parameters.v]
if {![file exists $parameters_file]} {
 error "Missing $parameters_file; the model parameters must come from the selected generated-data directory."
}
add_design $parameters_file
foreach path [glob [file join $generated_data_dir *.mem] [file join $generated_data_dir *.vh]] {file copy -force $path $output}
add_constraint [file join $root board training.fdc]
add_constraint [file join $root board ro_timing.fdc]
add_constraint [file join $root board ro_locations.fdc]
compile -top_module kosmo_training_top -include_path [list $generated_data_dir $output [file join $cnn generated]] -verilog_standard Verilog_2001
set f [open [file join $output prj_tasks syn_1 compile run.log] r]
set compile_log [read $f]
close $f
if {![regexp {Found Verilog include file ([^\n]*puf_key\.mem)} $compile_log -> key_used] ||
    [string tolower [file normalize [string trim $key_used]]] ne [string tolower [file normalize $key_file]]} {
 error "Compile did not read the key ROM from $key_file"
}
proc finish_build {output finish_marker} {
 dev_map
 place
 route
 route_optimize
 report_timing
 set f [open [file join $output prj_tasks pnr_1 report_timing kosmo_training_top.rtr] r]
 set report [read $f]
 close $f
 if {![regexp {Design Summary\s*:\s*All Constraints Met\.} $report]} {error "Board timing failed"}
 gen_netlist
 gen_bit_stream
 puts $finish_marker
}
