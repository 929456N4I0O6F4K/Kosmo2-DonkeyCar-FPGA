`timescale 1ns/1ps
`default_nettype none
// A single frozen camera frame is read first by crop/CNN, then by DMA.
// DMA alone releases the camera. Predictions stay immutable until that release.
module kosmo_cnn_bridge #(parameter PUF_ENABLE=0)(
 input wire clk,reset,frame_valid,frame_release,
 input wire [143:0] puf_mismatch,
 input wire puf_signs_valid,
 input wire [31:0] frame_sequence,
 input wire [15:0] dma_rd_addr,
 input wire [7:0] raw_q,
 output wire [15:0] raw_address,
 output reg inference_done,fault,
 output reg [31:0] prediction_sequence,prediction_cycles,prediction_status,
 output reg signed [31:0] prediction_angle,prediction_throttle
);
 reg started;
 wire ready,valid,timeout_fault,cnn_read;
 wire [15:0] cnn_address;
 reg [15:0] held_cnn_address;
 wire [31:0] result_sequence,cycles;
 wire signed [31:0] angle,throttle;
 // The existing camera RAM reads unconditionally. Hold its last enabled
 // address so the crop interface still sees clock-enable RAM semantics.
 assign raw_address=inference_done?dma_rd_addr:(cnn_read?cnn_address:held_cnn_address);
 camera_cnn_pipeline #(.PUF_ENABLE(PUF_ENABLE)) cnn(
 .clk(clk),.rst(reset),.frame_valid(frame_valid&&!started&&!frame_release),
 .puf_mismatch(puf_mismatch),.puf_signs_valid(puf_signs_valid),
 .frame_ready(ready),.frame_sequence(frame_sequence),.frame_consumed(),
 .raw_ce(cnn_read),.raw_address(cnn_address),.raw_q(raw_q),
 .result_valid(valid),.result_ready(1'b1),.result_sequence(result_sequence),
 .steering_q16(angle),.throttle_q16(throttle),.processing_cycles(cycles),
 .timeout_fault(timeout_fault),.result_expired());
 always @(posedge clk) begin
  if(reset)begin
   held_cnn_address<=0;
   started<=0;inference_done<=0;fault<=0;
   prediction_sequence<=0;prediction_cycles<=0;prediction_status<=0;
   prediction_angle<=0;prediction_throttle<=0;
  end else if(frame_release)begin
   started<=0;inference_done<=0;prediction_status<=0;
  end else begin
   if(cnn_read)held_cnn_address<=cnn_address;
   if(frame_valid&&!started&&ready)started<=1;
   if(started&&!inference_done)begin
    if(valid)begin
     prediction_sequence<=result_sequence;prediction_cycles<=cycles;
     prediction_angle<=angle;prediction_throttle<=throttle;
     prediction_status<=result_sequence==frame_sequence?32'd1:32'd2;
     inference_done<=1;
     if(result_sequence!=frame_sequence)fault<=1;
    end else if(timeout_fault)begin
     // Publish an explicitly invalid prediction so DMA/capture can progress.
     // Stop remains latched independently until a deliberate hardware reset.
     prediction_sequence<=frame_sequence;prediction_cycles<=2500000;
     prediction_angle<=0;prediction_throttle<=0;prediction_status<=2;
     inference_done<=1;fault<=1;
    end
   end
  end
 end
endmodule
`default_nettype wire
