`timescale 1ns/1ps
`default_nettype none
// Frame RAM is frozen at done; the system reads only after synchronizing done.
// Result buses stay stable until the next arm. No reset on the block RAM.
module camera_capture #(parameter integer WIDTH=160, HEIGHT=120)(
 input wire pclk, reset_async, arm, vsync, href, input wire [7:0] data,
 input wire rd_clk, input wire [15:0] rd_addr, output reg [7:0] rd_data,
 output reg done, good, output reg [31:0] byte_count,
 output reg [15:0] line_count, last_line_bytes,
 output reg [3:0] error_flags, output wire pclk_heartbeat,
 output wire capture_active
);
 localparam integer FRAME_BYTES=WIDTH*HEIGHT*2;
 (* syn_ramstyle="block_ram" *) reg [7:0] frame_mem [0:FRAME_BYTES-1];
 (* syn_preserve=1 *) reg [1:0] reset_sync=2'b11;
 (* syn_preserve=1 *) reg [1:0] arm_sync;
 reg vs_prev, href_prev, waiting, active;
 assign capture_active=active;
 reg [15:0] line_bytes;
 reg [9:0] heartbeat;
 wire reset_pclk=reset_sync[1];
 wire vs_rise=vsync && !vs_prev;
 wire line_end=href_prev && !href;
 wire [15:0] finished_lines=line_count + (line_end ? 16'd1 : 16'd0);
 assign pclk_heartbeat=heartbeat[9];
 always @(posedge pclk or posedge reset_async)
  if (reset_async) reset_sync<=2'b11; else reset_sync<={reset_sync[0],1'b0};
 always @(posedge rd_clk) rd_data<=frame_mem[rd_addr];
 always @(posedge pclk)
  if (!reset_pclk && arm_sync[1] && active && !vs_rise && href && byte_count<FRAME_BYTES)
   frame_mem[byte_count[15:0]]<=data;
 always @(posedge pclk or posedge reset_pclk) begin
  if (reset_pclk) begin
   arm_sync<=0; vs_prev<=0; href_prev<=0; waiting<=0; active<=0; done<=0; good<=0;
   byte_count<=0; line_count<=0; last_line_bytes<=0; line_bytes<=0; error_flags<=0; heartbeat<=0;
  end else begin
   arm_sync<={arm_sync[0],arm}; vs_prev<=vsync; href_prev<=href; heartbeat<=heartbeat+1'b1;
   if (!arm_sync[1]) begin waiting<=0; active<=0; done<=0; end
   else if (!waiting && !active && !done) begin
    waiting<=1; good<=0; error_flags<=0;
    byte_count<=0; line_count<=0; line_bytes<=0; last_line_bytes<=0;
   end else if (waiting && vs_rise) begin waiting<=0; active<=1; end
   else if (active) begin
    if (vs_rise) begin
     active<=0; done<=1; line_count<=finished_lines;
     if (line_end) last_line_bytes<=line_bytes;
     if (byte_count!=FRAME_BYTES) error_flags[0]<=1;
     if (finished_lines!=HEIGHT) error_flags[1]<=1;
     if (href || (line_end && line_bytes!=WIDTH*2)) error_flags[2]<=1;
     good <= byte_count==FRAME_BYTES && finished_lines==HEIGHT && error_flags==0 && !href && (!line_end || line_bytes==WIDTH*2);
    end else begin
     // HREF qualifies pixels. VSYNC is a frame boundary, not a pixel gate:
     // the DSP output may keep VSYNC high during valid rows. Either VSYNC
     // polarity works when its rising edge is in blanking; dimensions and
     // HREF-at-boundary checks below still reject malformed frames.
     if (href) begin
      if (byte_count!=32'hffffffff) byte_count<=byte_count+1'b1;
      if (line_bytes!=16'hffff) line_bytes<=line_bytes+1'b1;
      if (byte_count>=FRAME_BYTES) error_flags[3]<=1;
     end
     if (line_end) begin
      if (line_count!=16'hffff) line_count<=line_count+1'b1;
      last_line_bytes<=line_bytes; line_bytes<=0;
      if (line_bytes!=WIDTH*2) error_flags[2]<=1;
     end
    end
   end
  end
 end
endmodule
`default_nettype wire

