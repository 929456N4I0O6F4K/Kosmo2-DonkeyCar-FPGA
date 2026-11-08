`timescale 1ns/1ps
`default_nettype none
module camera_top #(
 parameter integer CLOCK_HZ=50000000, UART_BAUD=115200, SCCB_HZ=100000,
 parameter integer WIDTH=160, HEIGHT=120, RESET_CYCLES=65536,
 parameter integer CAPTURE_TIMEOUT_CYCLES=CLOCK_HZ*5, ENABLE_JTAG=0
)(
 input wire sysclk_50, rstn, uart_rx,
 output wire uart_tx, output wire [4:0] led_n,
 input wire cam_pclk, cam_vsync, cam_href, input wire [7:0] cam_data,
 output wire cam_reset_n, inout wire cam_scl, cam_sda
);
 localparam integer FRAME_BYTES=WIDTH*HEIGHT*2;
 localparam IDLE=0, RESTART_WAIT=1, CAP_RESET=2, CAP_WAIT=3, SNAPSHOT=4,
 HEADER=5, RAM_WAIT=6, PAYLOAD=7, CRC=8, DRAIN=9;
 reg [3:0] state=IDLE;
 reg [31:0] por_count=0;
 (* syn_preserve=1 *) reg [1:0] reset_sync=0;
 wire rst=(por_count<RESET_CYCLES) || !reset_sync[1];
 always @(posedge sysclk_50) if (por_count<RESET_CYCLES) por_count<=por_count+1'b1;
 always @(posedge sysclk_50 or negedge rstn)
  if (!rstn) reset_sync<=0; else reset_sync<={reset_sync[0],1'b1};
 reg [7:0] restart_count, cancel_count;
 wire cfg_reset=rst || (restart_count!=0);
 reg colorbar;
 wire cfg_ready, cfg_failed, id_ok;
 wire [7:0] pid, ver, cfg_error;
 wire [8:0] cfg_index;
 wire [39:0] cfg_debug;
 camera_config #(.CLOCK_HZ(CLOCK_HZ),.BUS_HZ(SCCB_HZ)) config_unit(
  .clk(sysclk_50),.rst(cfg_reset),.colorbar(colorbar),.cam_reset_n(cam_reset_n),
  .ready(cfg_ready),.failed(cfg_failed),.id_ok(id_ok),.pid(pid),.ver(ver),
  .error_code(cfg_error),.config_index(cfg_index),.scl(cam_scl),.sda(cam_sda),.debug_sccb(cfg_debug));
 wire [7:0] uart_rx_data, debug_rx_data;
 wire uart_rx_valid, debug_rx_valid, rx_error, tx_ready;
 wire [7:0] rx_data=debug_rx_valid ? debug_rx_data : uart_rx_data;
 wire rx_valid=debug_rx_valid || (!ENABLE_JTAG && uart_rx_valid);
 reg [7:0] tx_data;
 wire tx_valid=(state==HEADER || state==PAYLOAD || state==CRC);
 uart_rx #(.CLOCK_HZ(CLOCK_HZ),.BAUD_RATE(UART_BAUD)) receiver(
  .clk(sysclk_50),.rst(rst),.serial_in(uart_rx),.data_out(uart_rx_data),.data_valid(uart_rx_valid),.framing_error(rx_error));
 uart_tx #(.CLOCK_HZ(CLOCK_HZ),.BAUD_RATE(UART_BAUD)) transmitter(
  .clk(sysclk_50),.rst(rst),.data_in(tx_data),.data_valid(tx_valid),.data_ready(tx_ready),.serial_out(uart_tx));
 generate if (ENABLE_JTAG) begin : jtag_debug
  wire [31:0] control;
  wire [63:0] status;
  wire [2047:0] page_data;
  wire [255:0] monitor_report;
  camera_monitor #(.CLOCK_HZ(CLOCK_HZ),.WIDTH(WIDTH),.HEIGHT(HEIGHT)) monitor(
   .clk(sysclk_50),.pclk(cam_pclk),.reset(cfg_reset || !cfg_ready),
   .vsync(cam_vsync),.href(cam_href),.report(monitor_report));
  camera_dvio dvio(.clk(sysclk_50),.resetn(!rst),.control(control),.status(status),.page_data(page_data),
   .diagnostics({16'h5343,cfg_error,cfg_debug}),.monitor_report(monitor_report));
  camera_jtag_bridge #(.MAX_BYTES(FRAME_BYTES+44),.PAGE_SHIFT(8)) bridge(
   .clk(sysclk_50),.rst(rst),.control(control),.status(status),.page_data(page_data),
   .idle(state==IDLE),.command_data(debug_rx_data),.command_valid(debug_rx_valid),
   .packet_data(tx_data),.packet_valid(tx_valid && tx_ready));
 end else begin : no_jtag
  assign debug_rx_data=0;
  assign debug_rx_valid=0;
 end endgenerate
 reg capture_arm;
 wire cap_done, cap_good, pclk_heartbeat;
 wire [31:0] cap_bytes;
 wire [15:0] cap_lines, cap_last_line;
 wire [3:0] cap_errors;
 reg [15:0] rd_addr;
 wire [7:0] rd_data;
 camera_capture #(.WIDTH(WIDTH),.HEIGHT(HEIGHT)) capture(
  .pclk(cam_pclk),.reset_async(rst || !cfg_ready || (cancel_count!=0)),.arm(capture_arm),
  .vsync(cam_vsync),.href(cam_href),.data(cam_data),.rd_clk(sysclk_50),.rd_addr(rd_addr),
  .rd_data(rd_data),.done(cap_done),.good(cap_good),.byte_count(cap_bytes),
  .line_count(cap_lines),.last_line_bytes(cap_last_line),.error_flags(cap_errors),.pclk_heartbeat(pclk_heartbeat));
 (* syn_preserve=1 *) reg [2:0] done_sync;
 (* syn_preserve=1 *) reg [2:0] beat_sync, vs_sync, href_sync;
 reg pclk_seen, vs_seen, href_seen;
 reg [31:0] vs_count, bad_count, heartbeat_count;
 reg [31:0] last_bytes;
 reg [15:0] last_lines, last_line;
 reg [3:0] last_errors;
 reg last_good;
 wire [7:0] flags={colorbar,href_seen,vs_seen,pclk_seen,last_good,id_ok,cfg_failed,cfg_ready};
 assign led_n=~{(cfg_failed ? heartbeat_count[22] : last_good),vs_seen,cfg_ready,id_ok,heartbeat_count[24]};
 always @(posedge sysclk_50) begin
  if (rst) begin done_sync<=0; beat_sync<=0; vs_sync<=0; href_sync<=0; end
  else begin
   done_sync<={done_sync[1:0],cap_done}; beat_sync<={beat_sync[1:0],pclk_heartbeat};
   vs_sync<={vs_sync[1:0],cam_vsync}; href_sync<={href_sync[1:0],cam_href};
  end
  if (cfg_reset) begin pclk_seen<=0; vs_seen<=0; href_seen<=0; vs_count<=0; end
  else begin
   if (beat_sync[2]!=beat_sync[1]) pclk_seen<=1;
   if (vs_sync[2]!=vs_sync[1]) vs_seen<=1;
   if (href_sync[2]!=href_sync[1]) href_seen<=1;
   if (vs_sync[1] && !vs_sync[2]) vs_count<=vs_count+1'b1;
  end
  if (rst) heartbeat_count<=0; else heartbeat_count<=heartbeat_count+1'b1;
 end
 // Packet: 40-byte little-endian header, RGB565 bytes (MSB first), CRC32 LE.
 reg [319:0] header;
 reg [5:0] header_index;
 reg [1:0] crc_index;
 reg [31:0] crc_acc;
 reg [15:0] sequence;
 reg [7:0] packet_kind, packet_error;
 reg [31:0] payload_length, wait_count;
 function [31:0] crc32_byte;
  input [31:0] previous; input [7:0] value;
  reg [31:0] c; integer j;
  begin
   c=previous ^ {24'd0,value};
   for (j=0;j<8;j=j+1) c=c[0] ? (c>>1)^32'hedb88320 : c>>1;
   crc32_byte=c;
  end
 endfunction
 always @* begin
  case(state)
   HEADER: tx_data=header[header_index*8 +: 8];
   PAYLOAD: tx_data=rd_data;
   CRC: tx_data=~crc_acc[crc_index*8 +: 8];
   default: tx_data=8'hff;
  endcase
 end
 always @(posedge sysclk_50) begin
  if (rst) begin
   state<=IDLE; restart_count<=0; cancel_count<=0; colorbar<=0; capture_arm<=0;
   rd_addr<=0; last_bytes<=0; last_lines<=0; last_line<=0; last_errors<=0; last_good<=0;
   header<=0; header_index<=0; crc_index<=0; crc_acc<=32'hffffffff;
   sequence<=0; packet_kind<=1; packet_error<=0; payload_length<=0; wait_count<=0; bad_count<=0;
  end else begin
   if (restart_count!=0) restart_count<=restart_count-1'b1;
   if (cancel_count!=0) cancel_count<=cancel_count-1'b1;
   case(state)
    IDLE: begin
     capture_arm<=0;
     if (rx_valid) begin
      packet_kind<=1; payload_length<=0; packet_error<=cfg_error;
      case(rx_data)
       8'h53: state<=SNAPSHOT; // S: status
       8'h46: begin // F: a fresh, complete frame
        if (!cfg_ready) begin packet_kind<=3; packet_error<=4; state<=SNAPSHOT; end
        else begin
         last_good<=0; last_bytes<=0; last_lines<=0; last_line<=0; last_errors<=0;
         sequence<=sequence+1'b1; cancel_count<=32; state<=CAP_RESET;
        end
       end
       8'h52,8'h54,8'h4e: begin // R retry; T sensor color bars; N normal image
        if (rx_data==8'h54) colorbar<=1;
        if (rx_data==8'h4e) colorbar<=0;
        restart_count<=32; cancel_count<=32; last_good<=0; last_errors<=0;
        last_bytes<=0; last_lines<=0; last_line<=0; packet_error<=0; state<=RESTART_WAIT;
       end
       default: begin packet_kind<=3; packet_error<=7; state<=SNAPSHOT; end
      endcase
     end
    end
    RESTART_WAIT: if (restart_count==0) state<=SNAPSHOT;
    CAP_RESET: if (cancel_count==0) begin capture_arm<=1; wait_count<=0; state<=CAP_WAIT; end
    CAP_WAIT: begin
     if (done_sync[2]) begin
      // Bundled result has been stable for three sysclk edges before latching.
      capture_arm<=0; last_bytes<=cap_bytes; last_lines<=cap_lines;
      last_line<=cap_last_line; last_errors<=cap_errors; last_good<=cap_good;
      if (cap_good) begin packet_kind<=2; packet_error<=0; payload_length<=FRAME_BYTES; end
      else begin packet_kind<=3; packet_error<=5; payload_length<=0; bad_count<=bad_count+1'b1; end
      state<=SNAPSHOT;
     end else if (wait_count>=CAPTURE_TIMEOUT_CYCLES-1) begin
      capture_arm<=0; cancel_count<=32; packet_kind<=3; packet_error<=6;
      payload_length<=0; bad_count<=bad_count+1'b1; state<=SNAPSHOT;
     end else wait_count<=wait_count+1'b1;
    end
    SNAPSHOT: begin
     header[31:0]<=32'h314d4143; // wire bytes CAM1
     header[39:32]<=1; header[47:40]<=packet_kind; header[55:48]<=flags;
     header[63:56]<=packet_error; header[71:64]<=pid; header[79:72]<=ver;
     header[95:80]<=sequence; header[111:96]<=WIDTH; header[127:112]<=HEIGHT;
     header[159:128]<=payload_length; header[191:160]<=last_bytes;
     header[207:192]<=last_lines; header[223:208]<=last_line;
     header[239:224]<={7'd0,cfg_index}; header[247:240]<=1;
     header[255:248]<={4'd0,last_errors}; header[287:256]<=vs_count; header[319:288]<=bad_count;
     header_index<=0; crc_index<=0; rd_addr<=0; crc_acc<=32'hffffffff; state<=HEADER;
    end
    HEADER: if (tx_ready) begin
     crc_acc<=crc32_byte(crc_acc,tx_data);
     if (header_index==39) state<=payload_length!=0 ? RAM_WAIT : CRC;
     else header_index<=header_index+1'b1;
    end
    RAM_WAIT: state<=PAYLOAD;
    PAYLOAD: if (tx_ready) begin
     crc_acc<=crc32_byte(crc_acc,tx_data);
     if (rd_addr==FRAME_BYTES-1) begin crc_index<=0; state<=CRC; end
     else begin rd_addr<=rd_addr+1'b1; state<=RAM_WAIT; end
    end
    CRC: if (tx_ready) begin
     if (crc_index==3) state<=DRAIN; else crc_index<=crc_index+1'b1;
    end
    DRAIN: if (tx_ready) state<=IDLE;
    default: state<=IDLE;
   endcase
  end
 end
endmodule
`default_nettype wire

