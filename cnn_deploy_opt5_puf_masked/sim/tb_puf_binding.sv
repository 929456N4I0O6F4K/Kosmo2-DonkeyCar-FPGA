`timescale 1ns/1ps
module tb_puf_binding;
    reg clk=0;
    always #5 clk=~clk;
    reg rst=1;
    reg puf_active=1;
    reg [143:0] mismatch=0;
    wire idle,done,row_done,input_ce,parameter_ce,output_valid;
    wire [6:0] out_row,out_col,parameter_address;
    wire [16:0] input_address,output_address;
    wire [9:0] weight_address;
    wire channel_group;
    wire signed [7:0] output_value;

    mypilot_layer_engine #(.LANES(64),.PUF_ENABLE(1)) dut(
        .clk(clk),.rst(rst),.start(1'b0),.pixel_ready(1'b0),
        .cfg_taps(11'd1),.cfg_row_span(11'd1),.cfg_row_skip(17'd0),
        .cfg_stride_x(17'd0),.cfg_stride_y(17'd0),.cfg_ring_bytes(17'd0),
        .cfg_out_h(7'd1),.cfg_out_w(7'd1),.cfg_out_c(7'd1),
        .idle(idle),.done(done),.out_row(out_row),.out_col(out_col),
        .row_done(row_done),.input_ce(input_ce),.input_address(input_address),
        .input_q(8'h81),.weight_address(weight_address),.weight_q(512'b0),
        .bias_q(2048'b0),.channel_group(channel_group),
        .parameter_ce(parameter_ce),.parameter_address(parameter_address),
        .parameter_q(48'b0),.puf_sign_active(puf_active),.puf_mismatch(mismatch),
        .output_valid(output_valid),.output_value(output_value),
        .output_address(output_address));

    initial begin
        repeat(2) @(negedge clk);
        rst=0;
        @(negedge clk);
        // Stability masking and key mode are checked in tb_puf_key_store.
        dut.puf_comp.sign_idx_d=0;
        #1;
        if (dut.puf_negate !== 1'b0)
            $fatal(1,"Matching board-A sign changed the opt4 MAC");
        mismatch[0]=1'b1;
        #1;
        if (dut.puf_negate !== 1'b1)
            $fatal(1,"PUF mismatch did not alter a stable MAC sign");
        dut.puf_comp.sign_idx_d=3;
        #1;
        if (dut.puf_negate !== 1'b0)
            $fatal(1,"Mismatch at another tap affected this MAC");
        dut.puf_comp.sign_idx_d=0;
        puf_active=0;
        #1;
        if (dut.puf_negate !== 1'b0)
            $fatal(1,"PUF negation outside dense layers");
        $display("PUF_BINDING PASS match=unchanged mismatch=active other_tap=ignored inactive=ignored");
        $finish;
    end
    initial begin #1000; $fatal(1,"PUF binding watchdog"); end
endmodule
