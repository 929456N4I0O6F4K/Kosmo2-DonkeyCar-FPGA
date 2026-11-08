`timescale 1ns/1ps
`default_nettype none
// Continuous request/release adapter around the existing verified capture RAM.
// All applied_* inputs are in clk domain and describe accepted effective values.
// The frame-start edge crosses PCLK -> clk through three synchronizer stages;
// timestamp and labels refer to its detection in the 50 MHz system domain.
module kosmo_training_camera #(
 parameter integer WIDTH=160,HEIGHT=120,CLOCK_HZ=50000000
)(
 input wire clk,reset,camera_ready,
 input wire pclk,vsync,href,input wire [7:0] data,
 input wire [31:0] applied_sequence,applied_flags,
 input wire signed [31:0] applied_angle,applied_throttle,
 output reg frame_valid,input wire frame_release,
 input wire [15:0] frame_rd_addr,output wire [7:0] frame_rd_data,
 output reg [31:0] frame_sequence,frame_command_sequence,frame_flags,frame_dropped,
 output reg signed [31:0] frame_angle,frame_throttle,
 output reg [63:0] frame_ticks,
 output reg fault
);
 reg arm;
 wire done,good,active;
 wire cap_reset=reset||!camera_ready||fault;
 camera_capture #(.WIDTH(WIDTH),.HEIGHT(HEIGHT)) capture(
 .pclk(pclk),.reset_async(cap_reset),.arm(arm),.vsync(vsync),.href(href),.data(data),
 .rd_clk(clk),.rd_addr(frame_rd_addr),.rd_data(frame_rd_data),.done(done),.good(good),
 .byte_count(),.line_count(),.last_line_bytes(),.error_flags(),.pclk_heartbeat(),.capture_active(active));
 (* syn_preserve=1 *) reg [2:0] done_sync,active_sync;
 reg active_prev;
 reg [1:0] state;
 reg [63:0] ticks;
 reg [31:0] timeout_count;
 always @(posedge clk)begin
  if(reset)begin
   done_sync<=0;active_sync<=0;active_prev<=0;arm<=0;state<=0;ticks<=0;timeout_count<=0;
   frame_valid<=0;frame_sequence<=0;frame_command_sequence<=0;frame_flags<=0;frame_dropped<=0;
   frame_angle<=0;frame_throttle<=0;frame_ticks<=0;fault<=0;
  end else begin
   ticks<=ticks+1;
   done_sync<={done_sync[1:0],done};active_sync<={active_sync[1:0],active};active_prev<=active_sync[2];
   if(!camera_ready)begin arm<=0;frame_valid<=0;state<=0;timeout_count<=0;end
   else if(!fault)begin
    if(active_sync[2]&&!active_prev)begin
     frame_sequence<=frame_sequence+1;frame_ticks<=ticks;
     frame_command_sequence<=applied_sequence;frame_flags<=applied_flags;
     frame_angle<=applied_angle;frame_throttle<=applied_throttle;
    end
    case(state)
     0:if(!done_sync[2]&&!active_sync[2])begin arm<=1;timeout_count<=0;state<=1;end
     1:begin
      timeout_count<=timeout_count+1;
      if(done_sync[2])begin
       if(good)begin frame_valid<=1;state<=2;end
       else begin frame_dropped<=frame_dropped+1;arm<=0;state<=3;end
      end else if(timeout_count>=CLOCK_HZ)begin fault<=1;arm<=0;end
     end
     2:if(frame_release)begin frame_valid<=0;arm<=0;state<=3;end
     3:if(!done_sync[2]&&!active_sync[2])state<=0;
    endcase
   end
  end
 end
endmodule
`default_nettype wire
