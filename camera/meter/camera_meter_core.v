`timescale 1ns/1ps
// Static pin exerciser. SCCB pins only drive low or release to external pullups.
module camera_meter_core #(parameter CLOCK_HZ=50000000, parameter INTERNAL_PULLUPS=0)(
 input wire clk, resetn,
 input wire [31:0] control,
 inout wire cam_scl, cam_sda,
 output wire cam_reset_n,
 output wire [4:0] led_n,
 output wire [63:0] status
);
 reg [31:0] previous_control;
 reg [7:0] mode, token;
 reg command_error;
 reg [1:0] scl_sync, sda_sync;
 reg [31:0] beat_count;
 reg heartbeat;
 wire scl_low = resetn && (mode==2 || mode==4);
 wire sda_low = resetn && (mode==3 || mode==4);
 assign cam_scl = scl_low ? 1'b0 : 1'bz;
 assign cam_sda = sda_low ? 1'b0 : 1'bz;
 // 0: run/idle. Other modes hold the sensor in reset during line tests.
 assign cam_reset_n = resetn && mode==0;
 assign led_n = ~{(scl_low|sda_low), sda_sync[1], scl_sync[1], cam_reset_n, heartbeat};
 // Bit 16 identifies the physical-constraint profile; no active high driver.
 assign status = {16'h4d54,8'h01,mode,token,7'd0,(INTERNAL_PULLUPS!=0),8'd0,
                  command_error,cam_reset_n,sda_low,scl_low,sda_sync[1],scl_sync[1],heartbeat,resetn};
 always @(posedge clk or negedge resetn) begin
  if (!resetn) begin
   previous_control<=0; mode<=0; token<=0; command_error<=0;
   scl_sync<=0; sda_sync<=0; beat_count<=0; heartbeat<=0;
  end else begin
   scl_sync<={scl_sync[0],cam_scl}; sda_sync<={sda_sync[0],cam_sda};
   previous_control<=control;
   if (beat_count==CLOCK_HZ/2-1) begin beat_count<=0; heartbeat<=~heartbeat; end
   else beat_count<=beat_count+1'b1;
   // Require a settled, tagged word and a fresh token before changing outputs.
   if (control==previous_control && control[31:16]==16'h4d54 && control[15:8]!=token) begin
    token<=control[15:8];
    command_error<=control[7:0]>4;
    if (control[7:0]<=4) mode<=control[7:0];
   end
  end
 end
endmodule
