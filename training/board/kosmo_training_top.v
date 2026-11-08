`timescale 1ns/1ps
`default_nettype none
module kosmo_training_top(
 input wire sysclk_50,rstn,
 input wire cam_pclk,cam_vsync,cam_href,input wire [7:0] cam_data,
 output wire cam_reset_n,inout wire cam_scl,cam_sda,pca_scl,pca_sda,
 output wire [4:0] led_n
);
 reg [15:0] power_count=0;reg [1:0] reset_sync=0;
 always @(posedge sysclk_50 or negedge rstn)
  if(!rstn)begin power_count<=0;reset_sync<=0;end
  else begin if(!(&power_count))power_count<=power_count+1;reset_sync<={reset_sync[0],&power_count};end
 wire [31:0] debug_control;
 reg [1:0] debug_reset_sync=0;
 always @(posedge sysclk_50)debug_reset_sync<={debug_reset_sync[0],debug_control[0]};
 wire reset=!reset_sync[1]||debug_reset_sync[1];
 wire [31:0] awaddr,wdata,araddr,rdata;wire [3:0] wstrb;
 wire awvalid,awready,wvalid,wready,bvalid,bready,arvalid,arready,rvalid,rready;
 wire [1:0] bresp,rresp;
 wire [31:0] s_awaddr,s_araddr;wire [63:0] s_wdata,s_rdata;wire [7:0] s_wstrb;
 wire s_awvalid,s_awready,s_wvalid,s_wready,s_bvalid,s_bready,s_arvalid,s_arready,s_rvalid,s_rready;
 wire [1:0] s_bresp,s_rresp;wire pu_resetn;
 axi32_sps64 width_adapter(.clk(sysclk_50),.reset(reset),
 .awaddr(awaddr),.awvalid(awvalid),.awready(awready),.wdata(wdata),.wstrb(wstrb),.wvalid(wvalid),.wready(wready),.bresp(bresp),.bvalid(bvalid),.bready(bready),
 .araddr(araddr),.arvalid(arvalid),.arready(arready),.rdata(rdata),.rresp(rresp),.rvalid(rvalid),.rready(rready),
 .s_awaddr(s_awaddr),.s_awvalid(s_awvalid),.s_awready(s_awready),.s_wdata(s_wdata),.s_wstrb(s_wstrb),.s_wvalid(s_wvalid),.s_wready(s_wready),.s_bresp(s_bresp),.s_bvalid(s_bvalid),.s_bready(s_bready),
 .s_araddr(s_araddr),.s_arvalid(s_arvalid),.s_arready(s_arready),.s_rdata(s_rdata),.s_rresp(s_rresp),.s_rvalid(s_rvalid),.s_rready(s_rready));
 kosmo_pu_sps2 pu(.clk(sysclk_50),.resetn(pu_resetn),
 .awaddr(s_awaddr),.awvalid(s_awvalid),.awready(s_awready),.wdata(s_wdata),.wstrb(s_wstrb),.wvalid(s_wvalid),.wready(s_wready),.bresp(s_bresp),.bvalid(s_bvalid),.bready(s_bready),
 .araddr(s_araddr),.arvalid(s_arvalid),.arready(s_arready),.rdata(s_rdata),.rresp(s_rresp),.rvalid(s_rvalid),.rready(s_rready));
 wire camera_ready,camera_failed,control_valid,control_ack,control_stop;
 wire [31:0] control_sequence,control_flags,control_angle,control_throttle;
 wire [31:0] control_steering;
 wire [31:0] applied_sequence,applied_flags,applied_angle,applied_throttle;
 wire drive_ready,drive_fault,drive_active,drive_armed,shutdown_unconfirmed;
 wire [63:0] drive_diagnostics;
 wire [10:0] debug_state;
 kosmo_training_core core(.clk(sysclk_50),.reset(reset),
 .cam_pclk(cam_pclk),.cam_vsync(cam_vsync),.cam_href(cam_href),.cam_data(cam_data),.cam_reset_n(cam_reset_n),.cam_scl(cam_scl),.cam_sda(cam_sda),.camera_ready(camera_ready),.camera_failed(camera_failed),
 .control_valid(control_valid),.control_ack(control_ack),.control_health({26'd0,control_stop,shutdown_unconfirmed,drive_armed,drive_active,drive_fault,drive_ready}),.control_sequence(control_sequence),.control_flags(control_flags),.control_angle(control_angle),.control_throttle(control_throttle),.control_stop(control_stop),.debug_state(debug_state),
 .control_steering(control_steering),
 .applied_sequence(applied_sequence),.applied_flags(applied_flags),.applied_angle(applied_angle),.applied_throttle(applied_throttle),
 .m_awaddr(awaddr),.m_awvalid(awvalid),.m_awready(awready),.m_wdata(wdata),.m_wstrb(wstrb),.m_wvalid(wvalid),.m_wready(wready),.m_bresp(bresp),.m_bvalid(bvalid),.m_bready(bready),
 .m_araddr(araddr),.m_arvalid(arvalid),.m_arready(arready),.m_rdata(rdata),.m_rresp(rresp),.m_rvalid(rvalid),.m_rready(rready));
 // JTAG can reset the stopped integration core, but cannot issue drive commands.
 wire [63:0] status={16'h4b54,8'h08,7'd0,pu_resetn,debug_state[8:0],bresp,rresp,awvalid,wvalid,arvalid,
    s_awready,s_wready,s_arready,s_bvalid,s_rvalid,debug_state[10:9],
    camera_failed,camera_ready,shutdown_unconfirmed,drive_armed,drive_active,drive_fault,drive_ready,control_stop,control_valid};
 training_dvio dvio(.clk(sysclk_50),.resetn(reset_sync[1]),.status(status),.diagnostics(drive_diagnostics),.bus_debug({awaddr,araddr}),.control(debug_control));
 pca_drive_core drive(.clk(sysclk_50),.reset(reset),.stop(control_stop),
 .command_valid(control_valid),.command_ack(control_ack),.command_sequence(control_sequence),.command_flags(control_flags),.command_angle(control_angle),.command_throttle(control_throttle),
 .command_steering(control_steering),
 .applied_sequence(applied_sequence),.applied_flags(applied_flags),.applied_angle(applied_angle),.applied_throttle(applied_throttle),
 .scl(pca_scl),.sda(pca_sda),.ready(drive_ready),.fault(drive_fault),.active(drive_active),.armed(drive_armed),.shutdown_unconfirmed(shutdown_unconfirmed),.diagnostics(drive_diagnostics));
 assign led_n=~{drive_fault||camera_failed,control_stop,drive_active,camera_ready,drive_ready};
endmodule
`default_nettype wire
