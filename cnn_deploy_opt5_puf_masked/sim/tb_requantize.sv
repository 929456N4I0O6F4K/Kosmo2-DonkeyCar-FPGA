`timescale 1ns/1ps
module tb_requantize;
    `include "test_config.vh"
    reg clk = 0;
    always #5 clk = ~clk;
    reg rst = 1;
    reg valid_in = 0;
    reg signed [31:0] accumulator = 0;
    reg [47:0] parameters = 0;
    reg [16:0] tag_in = 0;
    reg last_in = 0;
    wire valid_out, last_out;
    wire signed [7:0] value_out;
    wire [16:0] tag_out;
    reg [87:0] vectors [0:QUANTIZER_CASES-1];
    reg simulation_passed = 0;
    integer sent, received = 0;
    mypilot_requantize dut (.*);

    always @(posedge clk) begin
        if (!rst && valid_out) begin
            if (tag_out !== received || value_out !== vectors[received][87:80])
                $fatal(1, "REQUANT mismatch vector=%0d tag=%0d actual=%0d expected=%0d",
                       received, tag_out, value_out, $signed(vectors[received][87:80]));
            if (last_out !== (received == QUANTIZER_CASES-1)) $fatal(1, "REQUANT last tag mismatch");
            received = received + 1;
        end
    end

    initial begin
        $readmemh("quantizer.mem", vectors);
        repeat (4) @(negedge clk);
        rst = 0;
        for (sent = 0; sent < QUANTIZER_CASES; sent = sent + 1) begin
            @(negedge clk);
            // Bubble boundaries exercise enable/metadata alignment.
            if (sent % 17 == 0) begin
                valid_in = 0;
                @(negedge clk);
            end
            valid_in = 1;
            accumulator = vectors[sent][31:0];
            parameters = vectors[sent][79:32];
            tag_in = sent;
            last_in = sent == QUANTIZER_CASES-1;
        end
        @(negedge clk);
        valid_in = 0;
        wait (received == QUANTIZER_CASES);
        @(negedge clk);
        simulation_passed = 1;
        $display("MYPILOT_REQUANT_RTL PASS vectors=%0d", received);
        $finish;
    end
    initial begin
        #1000000;
        $fatal(1, "REQUANT timeout");
    end
endmodule
