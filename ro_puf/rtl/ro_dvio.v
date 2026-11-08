`default_nettype none
module ro_dvio(input wire clk,resetn,input wire [63:0] status,diagnostics,batch_info,count_info,
 input wire [255:0] batch_data,batch_ties,input wire [1535:0] count_page,output wire [31:0] control);
 wire capture,drck,reset,selected,shift,update,tdi,tdo;
 GTP_SCANCHAIN_E1 scanchain(
  .TCK(),.TDI(),.TMS(),.TDO(),.CAPDR(capture),.JCLK(),.TCK_USER(drck),
  .TMS_USER(),.JRTI(),.RST(reset),.FLG_USER(selected),.SHFTDR(shift),
  .TDI_USER(tdi),.UPDR(update),.TDO_USER(tdo)) /* synthesis syn_noprune=1 */;
 wire dvio_clk,hub_tdi,capt,shift_d;
 wire [15:0] conf_sel,hub_tdo;
 wire [8:0] id;
 assign hub_tdo[15:1]=0;
 ips_dvio_jtag_hub_v1_0 #(.CTRL_PORT_NUM(1),.UJTAG_SEL(0)) hub(
  .urck_in(1'b0),.utdi_in(1'b0),.drck_in(drck),.tdi_in(tdi),.tdo_out(tdo),
  .reset_dr(reset),.shift_in(shift),.update_in(update),.capture_in(capture),
  .sel_in(selected),.h_rstn(resetn),.drck_o(dvio_clk),.conf_tdi(hub_tdi),
  .conf_sel(conf_sel),.id_o(id),.capt_o(capt),.shift_d(shift_d),.hub_tdo(hub_tdo));
 ips_dvio_v1_2 #(.PROBE_IN_PORT_NUM(12),.EN_ACTIVITY_DETECTOR(0),
  .PROBE_IN_PORT0_WIDTH(64),.PROBE_IN_PORT1_WIDTH(64),.PROBE_IN_PORT2_WIDTH(256),.PROBE_IN_PORT3_WIDTH(64),
  .PROBE_IN_PORT4_WIDTH(256),.PROBE_IN_PORT5_WIDTH(256),.PROBE_IN_PORT6_WIDTH(256),
  .PROBE_IN_PORT7_WIDTH(256),.PROBE_IN_PORT8_WIDTH(256),.PROBE_IN_PORT9_WIDTH(256),
  .PROBE_IN_PORT10_WIDTH(64),.PROBE_IN_PORT11_WIDTH(256),
  .PROBE_OUT_PORT_NUM(1),.PROBE_OUT_PORT0_WIDTH(32)) probes(
  .drck_in(dvio_clk),.hub_tdi(hub_tdi),.id_i(id),.capt_i(capt),.shift_i(shift_d),
  .conf_sel(conf_sel[0]),.hub_tdo(hub_tdo[0]),.clk(clk),.resetn_i(resetn),
  .probe_in0_i(status),.probe_in1_i(diagnostics),.probe_in2_i(batch_data),.probe_in3_i(batch_info),
  .probe_in4_i(count_page[255:0]),.probe_in5_i(count_page[511:256]),
  .probe_in6_i(count_page[767:512]),.probe_in7_i(count_page[1023:768]),
  .probe_in8_i(count_page[1279:1024]),.probe_in9_i(count_page[1535:1280]),
  .probe_in10_i(count_info),.probe_in11_i(batch_ties),.probe_out0(control));
endmodule
`default_nettype wire
