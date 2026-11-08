`timescale 1ns/1ps
`default_nettype none
// Explicit banks avoid rounding a whole frame to the next power of two.
// One synchronous read and one write; output bank select follows read enable.
module mypilot_banked_ram #(
    parameter BYTES=4096, BANK_BITS=12, DISTRIBUTED=0
) (
    input wire clk, write_enable, read_enable,
    input wire [16:0] write_address, read_address,
    input wire [7:0] write_data,
    output wire [7:0] read_data
);
    localparam BANKS=(BYTES+(1<<BANK_BITS)-1)/(1<<BANK_BITS);
    localparam SELECT_BITS=BANKS>1 ? $clog2(BANKS) : 1;
    wire [7:0] bank_q [0:BANKS-1];
    reg [SELECT_BITS-1:0] selected_bank;
    always @(posedge clk) if (read_enable) selected_bank <= read_address >> BANK_BITS;
    assign read_data = bank_q[selected_bank];
    genvar bank;
    generate for (bank=0; bank<BANKS; bank=bank+1) begin : banks
        wire wr = write_enable && (write_address >> BANK_BITS) == bank;
        wire rd = read_enable && (read_address >> BANK_BITS) == bank;
        if (DISTRIBUTED) begin : lut_storage
            (* ram_style="distributed", syn_ramstyle="select_ram" *)
            reg [7:0] memory [0:(1<<BANK_BITS)-1];
            reg [7:0] q;
            always @(posedge clk) begin
                if (wr) memory[write_address[BANK_BITS-1:0]] <= write_data;
                if (rd) q <= memory[read_address[BANK_BITS-1:0]];
            end
            assign bank_q[bank] = q;
        end else begin : block_storage
            (* ram_style="block", syn_ramstyle="block_ram" *)
            reg [7:0] memory [0:(1<<BANK_BITS)-1];
            reg [7:0] q;
            always @(posedge clk) begin
                if (wr) memory[write_address[BANK_BITS-1:0]] <= write_data;
                if (rd) q <= memory[read_address[BANK_BITS-1:0]];
            end
            assign bank_q[bank] = q;
        end
    end endgenerate
endmodule
`default_nettype wire
