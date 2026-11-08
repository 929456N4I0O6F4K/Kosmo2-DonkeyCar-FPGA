`timescale 1ns/1ps
module tb_puf_enroll;
    reg clk=0;
    always #10 clk=~clk;
    reg rst=1;
    reg ready=0;
    reg [143:0] expected=0;
    reg trigger_d=0;
    integer trigger_count=0;
    integer c,b;
    wire trigger,enroll_done,enroll_fault,signs_valid;
    wire [127:0] challenge;
    wire [143:0] signs;
    reg [8:0] fixture_response;

    always @* begin
        for (integer bit_index=0; bit_index<9; bit_index=bit_index+1)
            fixture_response[bit_index] = expected[enroll.chal_idx*9+bit_index] ^
                ((enroll.repeat_idx<2 && bit_index==0) ||
                 (enroll.repeat_idx==4 && bit_index==8));
    end

    always @(posedge clk) begin
        ready <= trigger;
        trigger_d <= trigger;
        if (trigger && !trigger_d) trigger_count <= trigger_count+1;
    end

    puf_auto_enroll #(.REPEAT_COUNT(5)) enroll(
        .clk(clk),.rst(rst),.puf_trigger(trigger),.puf_challenge(challenge),
        .puf_ready(ready),.puf_response(fixture_response[7:0]),
        .puf_xor(fixture_response[8]),.enroll_done(enroll_done),
        .enroll_fault(enroll_fault),.signs_valid(signs_valid),.sign_bits(signs));

    initial begin
        for (c=0; c<16; c=c+1)
            for (b=0; b<9; b=b+1)
                expected[c*9+b] = ((c*3+b*5+1)%7)<3;
        repeat(5) @(negedge clk);
        rst=0;
        wait(enroll_done);
        @(negedge clk);
        if (!signs_valid || enroll_fault) $fatal(1,"Enrollment did not finish cleanly");
        if (signs !== expected) $fatal(1,"Majority vote failed: %h != %h",signs,expected);
        if (trigger_count != 80) $fatal(1,"Expected 80 PUF evaluations, got %0d",trigger_count);
        rst=1;
        repeat(2) @(negedge clk);
        if (signs !== 144'b0 || signs_valid)
            $fatal(1,"Reset did not clear volatile PUF enrollment state");
        rst=0;
        wait(enroll_done);
        @(negedge clk);
        if (!signs_valid || signs !== expected)
            $fatal(1,"Re-enrollment did not restore the stable response vector");
        if (trigger_count != 160) $fatal(1,"Expected 160 total evaluations after re-enrollment, got %0d",trigger_count);
        $display("PUF_ENROLL_MAJORITY PASS challenges=16 samples=5 reenroll=stable evaluations=%0d",trigger_count);
        $finish;
    end
    initial begin #10000000; $fatal(1,"PUF enrollment watchdog"); end
endmodule
