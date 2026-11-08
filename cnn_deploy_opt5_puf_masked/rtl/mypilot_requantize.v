`timescale 1ns/1ps
`default_nettype none
// TFLite two-rounding integer requantization, one result per clock.
// Multiplier is positive; the exporter checks shift is in -31..0.
module mypilot_requantize (
    input wire clk,
    input wire rst,
    input wire valid_in,
    input wire signed [31:0] accumulator,
    input wire [47:0] parameters,
    input wire [16:0] tag_in,
    input wire last_in,
    output reg valid_out,
    output reg signed [7:0] value_out,
    output reg [16:0] tag_out,
    output reg last_out
);
    reg [3:0] valid_pipe;
    reg [3:0] last_pipe;
    reg [16:0] tag_pipe [0:3];
    reg [4:0] shift_1, shift_2;
    reg signed [7:0] zp_1, zp_2, zp_3;
    reg relu_1, relu_2, relu_3;
    (* use_dsp = "yes" *) reg signed [63:0] product;
    reg signed [31:0] high_product;
    reg signed [31:0] rounded;
    reg signed [32:0] with_zero_point;
    reg signed [32:0] lower_bound;
    integer stage;

    function signed [31:0] rounding_divide_by_pot;
        input signed [31:0] value;
        input [4:0] exponent;
        reg [31:0] mask, remainder, threshold;
        begin
            mask = (32'h00000001 << exponent) - 1'b1;
            remainder = value & mask;
            threshold = (mask >> 1) + {31'b0, value[31]};
            rounding_divide_by_pot = (value >>> exponent) + $signed({31'b0, remainder > threshold});
        end
    endfunction

    always @(posedge clk) begin
        if (rst) begin
            valid_pipe <= 0;
            valid_out <= 0;
            last_pipe <= 0;
            last_out <= 0;
        end else begin
            valid_pipe <= {valid_pipe[2:0], valid_in};
            valid_out <= valid_pipe[3];
            last_pipe <= {last_pipe[2:0], last_in};
            last_out <= last_pipe[3];
            tag_pipe[0] <= tag_in;
            for (stage = 1; stage < 4; stage = stage + 1)
                tag_pipe[stage] <= tag_pipe[stage-1];
            tag_out <= tag_pipe[3];

            if (valid_in) begin
                product <= accumulator * $signed(parameters[31:0]);
                shift_1 <= parameters[36:32];
                relu_1 <= parameters[37];
                zp_1 <= parameters[45:38];
            end
            if (valid_pipe[0]) begin
                // Positive multipliers exclude INT_MIN * INT_MIN overflow.
                // This arithmetic shift exactly implements SRDHM's asymmetric tie.
                high_product <= (product + 64'sd1073741824) >>> 31;
                shift_2 <= shift_1;
                relu_2 <= relu_1;
                zp_2 <= zp_1;
            end
            if (valid_pipe[1]) begin
                rounded <= rounding_divide_by_pot(high_product, shift_2);
                relu_3 <= relu_2;
                zp_3 <= zp_2;
            end
            if (valid_pipe[2]) begin
                with_zero_point <= $signed({rounded[31], rounded}) + $signed({{25{zp_3[7]}}, zp_3});
                lower_bound <= relu_3 ? $signed({{25{zp_3[7]}}, zp_3}) : -33'sd128;
            end
            if (valid_pipe[3]) begin
                if (with_zero_point > 33'sd127) value_out <= 8'sd127;
                else if (with_zero_point < lower_bound) value_out <= lower_bound[7:0];
                else value_out <= with_zero_point[7:0];
            end
        end
    end
endmodule
`default_nettype wire
