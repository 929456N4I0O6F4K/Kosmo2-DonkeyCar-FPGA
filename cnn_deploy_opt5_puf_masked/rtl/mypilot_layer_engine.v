`timescale 1ns/1ps
`default_nettype none
// One input tap per cycle, LANES output-channel MACs. Synchronous input/ROM.
// Permission is checked before each pixel; a granted pixel writes without stalls.
module mypilot_layer_engine #(parameter LANES = 64, parameter PUF_ENABLE = 0) (
    input wire clk, rst, start, pixel_ready,
    input wire [10:0] cfg_taps, cfg_row_span,
    input wire [16:0] cfg_row_skip, cfg_stride_x, cfg_stride_y, cfg_ring_bytes,
    input wire [6:0] cfg_out_h, cfg_out_w, cfg_out_c,
    output wire idle, output reg done,
    output reg [6:0] out_row, out_col,
    output wire row_done,
    output wire input_ce, output reg [16:0] input_address,
    input wire [7:0] input_q,
    output wire [9:0] weight_address,
    input wire [LANES*8-1:0] weight_q,
    input wire [LANES*32-1:0] bias_q,
    output reg channel_group,
    output wire parameter_ce, output wire [6:0] parameter_address,
    input wire [47:0] parameter_q,
    input wire puf_sign_active,
    input wire [143:0] puf_mismatch,
    output wire output_valid, output wire signed [7:0] output_value,
    output wire [16:0] output_address
);
    localparam IDLE=0, PIXEL=1, MAC=2, DRAIN=3, QUANT_FEED=4, QUANT_WAIT=5;
    reg [2:0] state;
    reg [16:0] window_base, row_base, output_base;
    reg [10:0] tap_index, row_tap;
    reg [5:0] quant_lane;
    wire [6:0] lanes_used = cfg_out_c > LANES ?
        (channel_group ? cfg_out_c-LANES : LANES) : cfg_out_c;
    assign idle = state == IDLE;
    assign input_ce = state == MAC;
    assign weight_address = tap_index[9:0];
    assign parameter_ce = state == QUANT_FEED;
    assign parameter_address = (channel_group ? LANES : 0) + quant_lane;
    wire signed [8:0] activation_centered = $signed({1'b0, input_q ^ 8'h80});
    wire puf_negate;
    generate
        if (PUF_ENABLE) begin : puf_comp
            reg [7:0] sign_idx, sign_idx_d;
            always @(posedge clk) begin
                if (rst || state == PIXEL) begin
                    sign_idx <= 0;
                    sign_idx_d <= 0;
                end else if (input_ce) begin
                    sign_idx_d <= sign_idx;
                    sign_idx <= sign_idx == 143 ? 0 : sign_idx + 1'b1;
                end
            end
            // puf_mismatch is already masked by the stability mask and the
            // key mode (kosmo_training_top); 0 everywhere preserves opt4.
            assign puf_negate = puf_sign_active && puf_mismatch[sign_idx_d];
        end else begin : no_puf_comp
            assign puf_negate = 1'b0;
        end
    endgenerate
    wire signed [8:0] activation = puf_negate ? -activation_centered
                                              : activation_centered;
    reg read_valid, read_first, read_last;
    reg product_valid, product_first, product_last;
    wire signed [31:0] accumulators [0:LANES-1];
    genvar lane;
    generate for (lane=0; lane<LANES; lane=lane+1) begin : mac_lanes
        (* use_dsp="yes", syn_multstyle="block_mult" *) reg signed [16:0] product;
        reg signed [31:0] accumulator;
        wire signed [7:0] weight_value = weight_q[lane*8 +: 8];
        wire signed [31:0] bias_value = bias_q[lane*32 +: 32];
        always @(posedge clk) begin
            if (read_valid) product <= activation * weight_value;
            if (product_valid) begin
                if (product_first) accumulator <= bias_value + product;
                else accumulator <= accumulator + product;
            end
        end
        assign accumulators[lane] = accumulator;
    end endgenerate
    reg quant_input_valid, quant_input_last;
    reg signed [31:0] quant_accumulator;
    reg [16:0] quant_tag;
    wire output_last;
    mypilot_requantize quantizer (
        .clk(clk), .rst(rst), .valid_in(quant_input_valid),
        .accumulator(quant_accumulator), .parameters(parameter_q),
        .tag_in(quant_tag), .last_in(quant_input_last),
        .valid_out(output_valid), .value_out(output_value),
        .tag_out(output_address), .last_out(output_last)
    );
    assign row_done = output_valid && output_last && out_col == cfg_out_w-1 &&
                      (cfg_out_c <= LANES || channel_group);
    function [16:0] wrap_address;
        input [17:0] address;
        begin
            wrap_address = cfg_ring_bytes != 0 && address >= cfg_ring_bytes ?
                           address-cfg_ring_bytes : address;
        end
    endfunction
    always @(posedge clk) begin
        if (parameter_ce) begin
            quant_accumulator <= accumulators[quant_lane];
            quant_tag <= output_base + parameter_address;
            quant_input_last <= {1'b0,quant_lane} == lanes_used-1;
        end
        if (rst) begin
            state <= IDLE; done <= 0; channel_group <= 0;
            out_row <= 0; out_col <= 0;
            read_valid <= 0; product_valid <= 0; quant_input_valid <= 0;
            read_first <= 0; read_last <= 0; product_first <= 0; product_last <= 0;
            tap_index <= 0; input_address <= 0;
        end else begin
            done <= 0;
            read_valid <= input_ce;
            read_first <= tap_index == 0;
            read_last <= tap_index == cfg_taps-1;
            product_valid <= read_valid;
            product_first <= read_first; product_last <= read_last;
            quant_input_valid <= parameter_ce;
            case (state)
                IDLE: if (start) begin
                    out_row <= 0; out_col <= 0; channel_group <= 0;
                    window_base <= 0; row_base <= 0; output_base <= 0;
                    state <= PIXEL;
                end
                PIXEL: if (pixel_ready) begin
                    input_address <= window_base; tap_index <= 0;
                    row_tap <= 0; quant_lane <= 0; state <= MAC;
                end
                MAC: begin
                    tap_index <= tap_index+1'b1;
                    if (row_tap == cfg_row_span-1) begin
                        row_tap <= 0;
                        input_address <= wrap_address({1'b0,input_address}+cfg_row_skip+18'd1);
                    end else begin
                        row_tap <= row_tap+1'b1;
                        input_address <= wrap_address({1'b0,input_address}+18'd1);
                    end
                    if (tap_index == cfg_taps-1) state <= DRAIN;
                end
                DRAIN: if (product_valid && product_last) state <= QUANT_FEED;
                QUANT_FEED: begin
                    quant_lane <= quant_lane+1'b1;
                    if ({1'b0,quant_lane} == lanes_used-1) state <= QUANT_WAIT;
                end
                QUANT_WAIT: if (output_valid && output_last) begin
                    if (cfg_out_c > LANES && !channel_group) begin
                        channel_group <= 1; state <= PIXEL;
                    end else if (out_col == cfg_out_w-1 && out_row == cfg_out_h-1) begin
                        done <= 1; state <= IDLE;
                    end else begin
                        channel_group <= 0;
                        output_base <= output_base + cfg_out_c;
                        if (out_col == cfg_out_w-1) begin
                            out_col <= 0; out_row <= out_row+1'b1;
                            row_base <= wrap_address({1'b0,row_base}+cfg_stride_y);
                            window_base <= wrap_address({1'b0,row_base}+cfg_stride_y);
                        end else begin
                            out_col <= out_col+1'b1;
                            window_base <= wrap_address({1'b0,window_base}+cfg_stride_x);
                        end
                        state <= PIXEL;
                    end
                end
                default: state <= IDLE;
            endcase
        end
    end
endmodule
`default_nettype wire
