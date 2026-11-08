`timescale 1ns/1ps
`default_nettype none
// Resource/timing harness, NOT a board pinout or a deployable car top.
// Includes one RGB565 frame RAM, crop RAM, and the complete CNN pipeline.
// A multiplexed report bus keeps every result observable during synthesis.
module pipeline_resource_top (
    input wire sysclk_50, rst,
    input wire raw_we,
    input wire [15:0] raw_waddress,
    input wire [7:0] raw_wdata,
    input wire frame_valid, result_ready,
    input wire [7:0] frame_sequence,
    input wire [2:0] report_select,
    output wire frame_ready, frame_consumed, result_valid, timeout_fault, result_expired,
    output reg [31:0] report
);
    (* syn_ramstyle="block_ram", ram_style="block" *) reg [7:0] raw_memory [0:38399];
    wire raw_ce;
    wire [15:0] raw_address;
    reg [7:0] raw_q;
    wire [31:0] result_sequence, processing_cycles;
    wire signed [31:0] steering_q16, throttle_q16;
    always @(posedge sysclk_50) begin
        if(raw_we && raw_waddress<38400) raw_memory[raw_waddress]<=raw_wdata;
        if(raw_ce) raw_q<=raw_memory[raw_address];
    end
    camera_cnn_pipeline pipeline(.clk(sysclk_50),.rst(rst),
        .frame_valid(frame_valid),.frame_ready(frame_ready),.frame_sequence({24'b0,frame_sequence}),
        .frame_consumed(frame_consumed),.raw_ce(raw_ce),.raw_address(raw_address),.raw_q(raw_q),
        .result_valid(result_valid),.result_ready(result_ready),.result_sequence(result_sequence),
        .steering_q16(steering_q16),.throttle_q16(throttle_q16),
        .processing_cycles(processing_cycles),.timeout_fault(timeout_fault),.result_expired(result_expired));
    always @* case(report_select)
        0: report=steering_q16;
        1: report=throttle_q16;
        2: report=processing_cycles;
        3: report=result_sequence;
        default: report={27'b0,result_expired,frame_ready,frame_consumed,result_valid,timeout_fault};
    endcase
endmodule
`default_nettype wire
