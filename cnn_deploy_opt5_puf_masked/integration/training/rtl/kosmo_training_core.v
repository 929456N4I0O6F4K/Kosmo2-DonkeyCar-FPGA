`timescale 1ns/1ps
`default_nettype none
// Fabric integration boundary: camera + frame transport + normalized controls.
// clk MUST be 50 MHz; reset is synchronous, active high in this domain.
// Vendor PU/PA AXI hard IP and the actuator core are instantiated by the board top.
module kosmo_training_core(
 input wire clk,reset,
 input wire [143:0] puf_mismatch,
 input wire puf_signs_valid,
 input wire cam_pclk,cam_vsync,cam_href,input wire [7:0] cam_data,
 output wire cam_reset_n,inout wire cam_scl,cam_sda,
 output wire camera_ready,camera_failed,
 output wire control_valid,input wire control_ack,
 input wire [31:0] control_health,
 output wire [31:0] control_sequence,control_flags,
 output wire [31:0] control_steering,
 output wire signed [31:0] control_angle,control_throttle,
 output wire control_stop,
 output wire [10:0] debug_state,
 input wire [31:0] applied_sequence,applied_flags,
 input wire signed [31:0] applied_angle,applied_throttle,
 output wire [31:0] m_awaddr,output wire m_awvalid,input wire m_awready,
 output wire [31:0] m_wdata,output wire [3:0] m_wstrb,
 output wire m_wvalid,input wire m_wready,
 input wire [1:0] m_bresp,input wire m_bvalid,output wire m_bready,
 output wire [31:0] m_araddr,output wire m_arvalid,input wire m_arready,
 input wire [31:0] m_rdata,input wire [1:0] m_rresp,input wire m_rvalid,output wire m_rready
);
 // OV2640 SIO_C is input-only; actively drive its clock while SDA stays open drain.
 wire exposure_valid,exposure_done;
 wire [31:0] exposure_setting,exposure_applied;wire [1:0] exposure_status;
 camera_config #(.CLOCK_HZ(50000000),.BUS_HZ(10000),.SCL_PUSH_PULL(1),.RUNTIME_EXPOSURE(1)) config_unit(
 .clk(clk),.rst(reset),.colorbar(1'b0),.cam_reset_n(cam_reset_n),
 .ready(camera_ready),.failed(camera_failed),.id_ok(),.pid(),.ver(),.error_code(),
 .config_index(),.scl(cam_scl),.sda(cam_sda),.debug_sccb(),
 .exposure_valid(exposure_valid),.exposure_setting(exposure_setting),.exposure_done(exposure_done),
 .exposure_status(exposure_status),.exposure_applied(exposure_applied));
 wire frame_valid,frame_release,capture_fault,transport_fault,transport_stop;
 wire [15:0] frame_rd_addr, dma_rd_addr;wire [7:0] frame_rd_data;
 wire dma_release, inference_done, cnn_fault;
 wire [31:0] prediction_sequence,prediction_cycles,prediction_status;
 wire signed [31:0] prediction_angle,prediction_throttle;
 wire [31:0] frame_sequence,frame_command_sequence,frame_flags,frame_dropped;
 wire signed [31:0] frame_angle,frame_throttle;wire [63:0] frame_ticks;
 assign debug_state[10:9]={transport_fault,capture_fault||cnn_fault};
 kosmo_cnn_bridge #(.PUF_ENABLE(1)) inference(
 .clk(clk),.reset(reset),.frame_valid(frame_valid),.frame_sequence(frame_sequence),
 .puf_mismatch(puf_mismatch),.puf_signs_valid(puf_signs_valid),
 .frame_release(dma_release),.dma_rd_addr(dma_rd_addr),.raw_q(frame_rd_data),
 .raw_address(frame_rd_addr),.inference_done(inference_done),.fault(cnn_fault),
 .prediction_sequence(prediction_sequence),.prediction_angle(prediction_angle),
 .prediction_throttle(prediction_throttle),.prediction_cycles(prediction_cycles),
 .prediction_status(prediction_status));
 assign frame_release=dma_release;
 assign control_stop=transport_stop||capture_fault||cnn_fault||camera_failed||!camera_ready||!puf_signs_valid;
 kosmo_training_camera camera(
 .clk(clk),.reset(reset),.camera_ready(camera_ready),.pclk(cam_pclk),.vsync(cam_vsync),.href(cam_href),.data(cam_data),
 .applied_sequence(applied_sequence),.applied_flags(control_stop?32'd0:applied_flags),
 .applied_angle(applied_angle),.applied_throttle(applied_throttle),
 .frame_valid(frame_valid),.frame_release(frame_release),.frame_rd_addr(frame_rd_addr),.frame_rd_data(frame_rd_data),
 .frame_sequence(frame_sequence),.frame_command_sequence(frame_command_sequence),.frame_flags(frame_flags),
 .frame_dropped(frame_dropped),.frame_angle(frame_angle),.frame_throttle(frame_throttle),.frame_ticks(frame_ticks),.fault(capture_fault));
 kosmo_training_transport transport(
 .clk(clk),.reset(reset),.frame_valid(frame_valid&&inference_done),.frame_sequence(frame_sequence),.frame_ticks(frame_ticks),
 .frame_command_sequence(frame_command_sequence),.frame_angle(frame_angle),.frame_throttle(frame_throttle),.frame_flags(frame_flags),.frame_dropped(frame_dropped),
 .frame_rd_addr(dma_rd_addr),.frame_rd_data(frame_rd_data),.frame_release(dma_release),
 .prediction_sequence(prediction_sequence),.prediction_angle(prediction_angle),
 .prediction_throttle(prediction_throttle),.prediction_cycles(prediction_cycles),
 .prediction_status(prediction_status),
 .control_valid(control_valid),.control_ack(control_ack),.control_sequence(control_sequence),.control_flags(control_flags),
 .control_steering(control_steering),
 .exposure_valid(exposure_valid),.exposure_setting(exposure_setting),.exposure_done(exposure_done),
 .exposure_status(exposure_status),.exposure_applied(exposure_applied),
 .exposure_allowed(applied_flags==0&&camera_ready&&!camera_failed),
 .control_angle(control_angle),.control_throttle(control_throttle),.control_health(control_health),.control_stop(transport_stop),.fault(transport_fault),.debug_state(debug_state[8:0]),
 .m_awaddr(m_awaddr),.m_awvalid(m_awvalid),.m_awready(m_awready),.m_wdata(m_wdata),.m_wstrb(m_wstrb),.m_wvalid(m_wvalid),.m_wready(m_wready),.m_bresp(m_bresp),.m_bvalid(m_bvalid),.m_bready(m_bready),
 .m_araddr(m_araddr),.m_arvalid(m_arvalid),.m_arready(m_arready),.m_rdata(m_rdata),.m_rresp(m_rresp),.m_rvalid(m_rvalid),.m_rready(m_rready));
endmodule
`default_nettype wire
