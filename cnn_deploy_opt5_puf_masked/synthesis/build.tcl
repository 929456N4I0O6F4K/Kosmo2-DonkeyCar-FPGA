set root [file normalize [file join [file dirname [info script]] ..]]
set output [file join $root build pds]
if {[string tolower [file normalize [pwd]]] ne [string tolower $output]} {
    error "Launch from $output"
}
set_arch -family Kosmo2 -device PG2K100 -speedgrade -6 -package MBG400
foreach path [glob [file join $root rtl *.v]] {add_design $path}
# RO array primitives live in ro_puf/rtl; rtl/ro_puf_enroll.v instantiates them.
set puf [file normalize [file join $root .. ro_puf rtl]]
foreach name {ro_cell ro_bank ro_counter} {add_design [file join $puf $name.v]}
add_design [file join $root rtl generated mypilot_parameters.v]
add_design [file join $root synthesis pipeline_resource_top.v]
add_constraint [file join $root synthesis pipeline.fdc]
compile -top_module pipeline_resource_top -include_path [list [file join $root rtl generated]] -verilog_standard Verilog_2001
synthesize -ads -selected_syn_tool_opt 2
dev_map
place
route
route_optimize
report_timing
puts CNN_RESOURCE_TIMING_FINISHED
