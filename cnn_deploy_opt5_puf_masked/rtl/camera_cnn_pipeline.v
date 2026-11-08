`timescale 1ns/1ps
`default_nettype none
// Frozen-frame interface. Frame ownership is acquired on valid && ready and
// released by frame_consumed. Busy frames are not queued: the producer may
// drop them, but must never overwrite the owned RAM before frame_consumed.
// Result backpressure does not retain camera RAM. An unread result expires
// after MAX_RESULT_HOLD_CYCLES, so an absent reader cannot deadlock capture.
module camera_cnn_pipeline #(parameter MAX_CYCLES=2500000,
    parameter PUF_ENABLE=0,
    parameter MAX_RESULT_HOLD_CYCLES=500000) (
    input wire clk, rst,
    input wire [143:0] puf_mismatch,
    input wire puf_signs_valid,
    input wire frame_valid,
    output wire frame_ready,
    input wire [31:0] frame_sequence,
    output reg frame_consumed,
    output wire raw_ce,
    output wire [15:0] raw_address,
    input wire [7:0] raw_q,
    output reg result_valid,
    input wire result_ready,
    output reg [31:0] result_sequence,
    output reg signed [31:0] steering_q16, throttle_q16,
    output reg [31:0] processing_cycles,
    output reg timeout_fault, result_expired
);
    localparam IDLE=0, CROP=1, LAUNCH=2, INFER=3, RECOVER=4;
    reg [2:0] state;
    reg [31:0] cycles, accepted_sequence, result_wait;
    reg crop_start, cnn_start;
    wire crop_done, crop_write, cnn_done, cnn_idle, image_ce;
    wire [16:0] crop_address;
    wire [7:0] crop_q, image_q;
    wire [15:0] image_address;
    wire signed [31:0] cnn_steering, cnn_throttle;
    wire local_reset=rst || state==RECOVER;
    assign frame_ready=state==IDLE && !result_valid && !rst;
    rgb565_crop crop(.clk(clk),.rst(local_reset),.start(crop_start),.idle(),.done(crop_done),
        .raw_ce(raw_ce),.raw_address(raw_address),.raw_q(raw_q),
        .write_valid(crop_write),.write_address(crop_address),.write_q(crop_q));
    mypilot_banked_ram #(.BYTES(44460)) image (
        .clk(clk),.write_enable(crop_write),.write_address(crop_address),.write_data(crop_q),
        .read_enable(image_ce),.read_address({1'b0,image_address}),.read_data(image_q));
    mypilot_cnn_core #(.PUF_ENABLE(PUF_ENABLE)) cnn(.clk(clk),.rst(local_reset),.start(cnn_start),.idle(cnn_idle),.done(cnn_done),
        .image_ce(image_ce),.image_address(image_address),.image_q(image_q),
        .steering_q16(cnn_steering),.throttle_q16(cnn_throttle),
        .puf_mismatch(puf_mismatch),.puf_signs_valid(puf_signs_valid));
    always @(posedge clk) begin
        if(rst) begin
            state<=IDLE; cycles<=0; accepted_sequence<=0;
            crop_start<=0; cnn_start<=0; frame_consumed<=0;
            result_valid<=0; result_sequence<=0; processing_cycles<=0;
            steering_q16<=0; throttle_q16<=0; timeout_fault<=0;
            result_wait<=0; result_expired<=0;
        end else begin
            crop_start<=0; cnn_start<=0; frame_consumed<=0;
            if(!result_valid || result_ready) result_wait<=0;
            else if(result_wait>=MAX_RESULT_HOLD_CYCLES-1) begin
                result_valid<=0; result_expired<=1; result_wait<=0;
                steering_q16<=0; throttle_q16<=0;
            end else result_wait<=result_wait+1'b1;
            if(result_valid && result_ready) result_valid<=0;
            if(state==CROP || state==LAUNCH || state==INFER) cycles<=cycles+1'b1;
            if((state==CROP || state==LAUNCH || state==INFER) && cycles>=MAX_CYCLES-1) begin
                if(state==CROP) frame_consumed<=1;
                state<=RECOVER; timeout_fault<=1; result_valid<=0;
                steering_q16<=0; throttle_q16<=0;
            end else case(state)
                IDLE: if(frame_valid && frame_ready) begin
                    accepted_sequence<=frame_sequence; cycles<=0; timeout_fault<=0;
                    crop_start<=1; state<=CROP; result_expired<=0;
                end
                CROP: if(crop_done) begin frame_consumed<=1; state<=LAUNCH; end
                LAUNCH: if(cnn_idle) begin cnn_start<=1; state<=INFER; end
                INFER: if(cnn_done) begin
                    result_sequence<=accepted_sequence; processing_cycles<=cycles+1'b1;
                    steering_q16<=cnn_steering; throttle_q16<=cnn_throttle;
                    result_valid<=1; state<=IDLE;
                end
                RECOVER: state<=IDLE;
                default: state<=RECOVER;
            endcase
        end
    end
endmodule
`default_nettype wire
