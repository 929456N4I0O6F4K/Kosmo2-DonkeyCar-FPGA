`timescale 1ns/1ps
module tb_crop_timeout;
    reg clk=0;
    always #10 clk=~clk;
    reg rst=1, frame_valid=0, result_ready=0;
    reg [143:0] puf_mismatch=0;
    reg puf_signs_valid=1;
    reg [31:0] frame_sequence=7;
    wire frame_ready, frame_consumed, raw_ce, result_valid, timeout_fault, result_expired;
    wire [15:0] raw_address;
    reg [7:0] raw_q=0;
    wire [31:0] result_sequence, processing_cycles;
    wire signed [31:0] steering_q16, throttle_q16;
    integer releases=0, faults=0;
    camera_cnn_pipeline #(.MAX_CYCLES(32)) dut(.*);
    always @(posedge clk) if(frame_consumed) releases=releases+1;
    initial begin
        repeat(4) @(negedge clk); rst=0;
        repeat(2) begin
            wait(frame_ready);
            @(negedge clk); frame_valid=1;
            @(negedge clk); frame_valid=0;
            wait(timeout_fault); faults=faults+1;
            repeat(4) @(negedge clk);
            if(!frame_ready || result_valid || releases!=faults) $fatal(1,"Crop timeout failed to release/reset");
        end
        $display("CROP_TIMEOUT PASS releases=%0d",releases); $finish;
    end
    initial begin #100000; $fatal(1,"Crop watchdog stuck"); end
endmodule
