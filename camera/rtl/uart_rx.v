`timescale 1ns/1ps
`default_nettype none
module uart_rx #(
    parameter integer CLOCK_HZ = 100000000,
    parameter integer BAUD_RATE = 2000000,
    parameter integer CLKS_PER_BIT = CLOCK_HZ / BAUD_RATE
) (
    input wire clk,
    input wire rst,
    input wire serial_in,
    output reg [7:0] data_out,
    output reg data_valid,
    output reg framing_error
);
    localparam IDLE = 2'd0;
    localparam START = 2'd1;
    localparam DATA = 2'd2;
    localparam STOP = 2'd3;

    (* ASYNC_REG = "TRUE" *) reg [1:0] sync_reg = 2'b11;
    reg [1:0] state = IDLE;
    reg [15:0] clock_count = 0;
    reg [2:0] bit_index = 0;

    always @(posedge clk) begin
        sync_reg <= {sync_reg[0], serial_in};
        data_valid <= 1'b0;
        framing_error <= 1'b0;
        if (rst) begin
            state <= IDLE;
            clock_count <= 0;
            bit_index <= 0;
            data_out <= 0;
        end else begin
            case (state)
                IDLE: begin
                    clock_count <= 0;
                    if (!sync_reg[1]) state <= START;
                end
                START: begin
                    if (clock_count == CLKS_PER_BIT / 2 - 1) begin
                        clock_count <= 0;
                        if (!sync_reg[1]) begin
                            bit_index <= 0;
                            state <= DATA;
                        end else begin
                            state <= IDLE;
                        end
                    end else begin
                        clock_count <= clock_count + 1'b1;
                    end
                end
                DATA: begin
                    if (clock_count == CLKS_PER_BIT - 1) begin
                        clock_count <= 0;
                        data_out[bit_index] <= sync_reg[1];
                        if (bit_index == 3'd7) state <= STOP;
                        else bit_index <= bit_index + 1'b1;
                    end else begin
                        clock_count <= clock_count + 1'b1;
                    end
                end
                STOP: begin
                    if (clock_count == CLKS_PER_BIT - 1) begin
                        clock_count <= 0;
                        state <= IDLE;
                        if (sync_reg[1]) data_valid <= 1'b1;
                        else framing_error <= 1'b1;
                    end else begin
                        clock_count <= clock_count + 1'b1;
                    end
                end
                default: state <= IDLE;
            endcase
        end
    end
endmodule
`default_nettype wire
