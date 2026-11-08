`timescale 1ns/1ps
`default_nettype none
// Sysclk-side mailbox. DVIO synchronizes its control output into this clock.
// control: [31:16] page, [15:8] command token, [7:0] ASCII command.
// status: CA01 = 32 bytes/page; CA02 = 256 bytes/page; then page/count/flags/token.
// Memory is frozen between commands. A complete packet includes its UART CRC.
module camera_jtag_bridge #(parameter integer MAX_BYTES=38444, PAGE_SHIFT=5)(
 input wire clk,rst, input wire [31:0] control, input wire idle,
 input wire [7:0] packet_data, input wire packet_valid,
 output reg [7:0] command_data, output reg command_valid,
 output wire [63:0] status, output reg [(8<<PAGE_SHIFT)-1:0] page_data
);
 (* ram_style="block" *) reg [7:0] memory [0:MAX_BYTES-1];
 reg [7:0] token;
 reg [15:0] byte_count, loaded_page;
 reg active,saw_busy,complete,overflow,page_ready;
 reg [1:0] read_state;
 reg [PAGE_SHIFT-1:0] offset;
 reg [15+PAGE_SHIFT:0] read_address;
 reg [7:0] read_byte;
 wire [15:0] requested_page=control[31:16];
 wire accept=idle && !active && !command_valid && control[15:8]!=token;
 localparam [15:0] SIGNATURE=PAGE_SHIFT==5 ? 16'hca01 : 16'hca02;
 assign status={SIGNATURE,loaded_page,byte_count,3'd0,page_ready,overflow,complete,active,idle,token};
 always @(posedge clk) begin
  if (packet_valid && active && byte_count<MAX_BYTES) memory[byte_count]<=packet_data;
  if (read_address<MAX_BYTES) read_byte<=memory[read_address]; else read_byte<=0;
 end
 always @(posedge clk) begin
  if (rst) begin
   token<=0; byte_count<=0; active<=0; saw_busy<=0; complete<=0; overflow<=0;
   command_valid<=0; command_data<=0; page_ready<=0; loaded_page<=16'hffff;
   read_state<=0; read_address<=0; offset<=0; page_data<=0;
  end else begin
   command_valid<=0;
   if (accept) begin
    token<=control[15:8]; command_data<=control[7:0]; command_valid<=1;
    active<=1; saw_busy<=0; complete<=0; overflow<=0; byte_count<=0;
   end else if (active) begin
    if (!idle) saw_busy<=1;
    if (packet_valid) begin
     if (byte_count<MAX_BYTES) byte_count<=byte_count+1'b1; else overflow<=1;
    end
    if (saw_busy && idle) begin active<=0; complete<=1; end
   end
   // Stop page reads during packet writes; reload even when page stays zero.
   if (accept || active || !complete) begin page_ready<=0; read_state<=0; end
   else if (page_ready && requested_page!=loaded_page) begin page_ready<=0; read_state<=0; end
   else if (!page_ready) begin
    case (read_state)
     0: begin loaded_page<=requested_page; offset<=0; read_address<={requested_page,{PAGE_SHIFT{1'b0}}}; read_state<=1; end
     1: read_state<=2; // synchronous RAM read
     2: begin
      page_data[offset*8 +: 8]<=read_byte;
      if (offset==(1<<PAGE_SHIFT)-1) begin page_ready<=1; read_state<=0; end
      else begin offset<=offset+1'b1; read_address<=read_address+1'b1; read_state<=1; end
     end
    endcase
   end
  end
 end
endmodule
`default_nettype wire
