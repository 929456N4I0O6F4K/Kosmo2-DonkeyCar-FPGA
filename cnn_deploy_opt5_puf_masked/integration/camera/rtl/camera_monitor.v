`timescale 1ns/1ps
`default_nettype none
// Observe every DVP frame, including frames not requested by the host.
// A toggle handshake freezes a coherent PCLK-domain snapshot once per second.
// Report: DV magic16, sample sequence16, sysclk ticks32, PCLK edges32,
// total frames32, bad frames32, last bytes32, lines16, last row bytes16,
// PCLK edges in last frame32. Counters wrap; host computes modular differences.
module camera_monitor #(
 parameter integer CLOCK_HZ=50000000, WIDTH=160, HEIGHT=120
)(
 input wire clk,pclk,reset,vsync,href,
 output reg [255:0] report
);
 localparam integer FRAME_BYTES=WIDTH*HEIGHT*2;
 (* syn_preserve=1 *) reg [1:0] reset_sync=2'b11;
 wire p_reset=reset_sync[1];
 always @(posedge pclk or posedge reset)
  if (reset) reset_sync<=2'b11; else reset_sync<={reset_sync[0],1'b0};

 reg request_toggle;
 (* syn_preserve=1 *) reg [1:0] request_sync;
 reg ack_toggle;
 reg [191:0] snapshot;
 reg vs_prev,href_prev,have_boundary,seen_vsync_low;
 reg [31:0] pclk_edges,frame_start,total_frames,bad_frames;
 reg [31:0] bytes_seen,last_bytes,last_frame_edges;
 reg [15:0] lines,line_bytes,current_last_row,last_lines,last_row_bytes;
 reg malformed;
 wire vs_rise=vsync && !vs_prev && seen_vsync_low;
 wire line_end=href_prev && !href;
 wire [16:0] finished_lines={1'b0,lines}+(line_end ? 17'd1 : 17'd0);
 wire frame_good=bytes_seen==FRAME_BYTES && finished_lines==HEIGHT &&
                 !malformed && !href && (!line_end || line_bytes==WIDTH*2);
 always @(posedge pclk or posedge p_reset) begin
  if (p_reset) begin
   request_sync<=0; ack_toggle<=0; snapshot<=0;
   vs_prev<=0; href_prev<=0; have_boundary<=0; seen_vsync_low<=0;
   pclk_edges<=0; frame_start<=0; total_frames<=0; bad_frames<=0;
   bytes_seen<=0; last_bytes<=0; last_frame_edges<=0;
   lines<=0; line_bytes<=0; current_last_row<=0; last_lines<=0; last_row_bytes<=0; malformed<=0;
  end else begin
   request_sync<={request_sync[0],request_toggle};
   vs_prev<=vsync; href_prev<=href; pclk_edges<=pclk_edges+1'b1;
   if (!vsync) seen_vsync_low<=1;
   if (request_sync[1]!=ack_toggle) begin
    snapshot<={pclk_edges,total_frames,bad_frames,last_bytes,last_lines,last_row_bytes,last_frame_edges};
    ack_toggle<=request_sync[1];
   end
   if (vs_rise) begin
    if (have_boundary) begin
     total_frames<=total_frames+1'b1;
     if (!frame_good) bad_frames<=bad_frames+1'b1;
     last_bytes<=bytes_seen; last_lines<=finished_lines[15:0];
     last_row_bytes<=line_end ? line_bytes : current_last_row;
     last_frame_edges<=pclk_edges-frame_start;
    end
    have_boundary<=1; frame_start<=pclk_edges;
    bytes_seen<=0; lines<=0; line_bytes<=0; current_last_row<=0; malformed<=href;
   end else if (have_boundary) begin
    if (href) begin
     if (bytes_seen!=32'hffffffff) bytes_seen<=bytes_seen+1'b1;
     if (line_bytes!=16'hffff) line_bytes<=line_bytes+1'b1;
     if (bytes_seen>=FRAME_BYTES || line_bytes==16'hffff) malformed<=1;
    end
    if (line_end) begin
     if (lines!=16'hffff) lines<=lines+1'b1; else malformed<=1;
     current_last_row<=line_bytes; line_bytes<=0;
     if (line_bytes!=WIDTH*2) malformed<=1;
    end
   end
  end
 end

 reg [31:0] sys_ticks,interval_count;
 reg [15:0] sample_sequence;
 (* syn_preserve=1 *) reg [2:0] ack_sync;
 reg acknowledged;
 always @(posedge clk) begin
  if (reset) begin
   sys_ticks<=0; interval_count<=0; sample_sequence<=0;
   request_toggle<=0; ack_sync<=0; acknowledged<=0;
   report<={16'h4456,240'd0};
  end else begin
   sys_ticks<=sys_ticks+1'b1; ack_sync<={ack_sync[1:0],ack_toggle};
   if (interval_count==CLOCK_HZ-1) begin
    interval_count<=0;
    if (request_toggle==acknowledged) request_toggle<=!request_toggle;
   end else interval_count<=interval_count+1'b1;
   if (ack_sync[2]!=acknowledged) begin
    acknowledged<=ack_sync[2]; sample_sequence<=sample_sequence+1'b1;
    report<={16'h4456,(sample_sequence+16'd1),sys_ticks,snapshot};
   end
  end
 end
endmodule
`default_nettype wire
