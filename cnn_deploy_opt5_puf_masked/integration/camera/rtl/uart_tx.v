`timescale 1ns/1ps
`default_nettype none
module uart_tx #(
    parameter integer CLOCK_HZ = 100000000,
    parameter integer BAUD_RATE = 2000000,
    parameter integer CLKS_PER_BIT = CLOCK_HZ / BAUD_RATE
) (
    input wire clk,
    input wire rst,
    input wire [7:0] data_in,
    input wire data_valid,
    output wire data_ready,
    output reg serial_out
);
    reg busy = 0;
    reg [9:0] frame = 10'h3ff;
    reg [3:0] bit_index = 0;
    reg [15:0] clock_count = 0;
    assign data_ready = !busy;

    always @(posedge clk) begin
        if (rst) begin
            busy <= 0;
            frame <= 10'h3ff;
            bit_index <= 0;
            clock_count <= 0;
            serial_out <= 1'b1;
        end else if (!busy) begin
            serial_out <= 1'b1;
            if (data_valid) begin
                frame <= {1'b1, data_in, 1'b0};
                busy <= 1'b1;
                bit_index <= 0;
                clock_count <= 0;
                serial_out <= 1'b0;
            end
        end else if (clock_count == CLKS_PER_BIT - 1) begin
            clock_count <= 0;
            if (bit_index == 4'd9) begin
                busy <= 0;
                serial_out <= 1'b1;
            end else begin
                bit_index <= bit_index + 1'b1;
                serial_out <= frame[bit_index + 1'b1];
            end
        end else begin
            clock_count <= clock_count + 1'b1;
        end
    end
endmodule
`default_nettype wire
