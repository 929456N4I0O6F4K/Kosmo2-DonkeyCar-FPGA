`timescale 1ns/1ps
module tb_ro_puf_enroll;
    reg clk=0, rst=1;
    always #10 clk=~clk;
    wire enable, clear, done, fault, valid;
    wire [4:0] select_a, select_b;
    wire [143:0] signs, quality;
    wire [15:0] generation;
    reg [23:0] count_a, count_b;
    reg overflow_a=0, overflow_b=0;
    integer mode=0, g, l;
    integer sample_count=0, enabled_cycles=0;
    reg [143:0] expected, expected_quality;
    reg bit_value;
    ro_puf_sampler #(.MEASURE_CYCLES(64),.REPEAT_COUNT(5),.MIN_MARGIN(5),
                     .CONTINUOUS(1),.CLEAR_CYCLES(3),.SETTLE_CYCLES(2),.DRAIN_CYCLES(5)) dut(
        .clk(clk),.rst(rst),.count_a(count_a),.count_b(count_b),
        .overflow_a(overflow_a),.overflow_b(overflow_b),
        .enable(enable),.clear(clear),.select_a(select_a),.select_b(select_b),
        .enroll_done(done),.enroll_fault(fault),.signs_valid(valid),
        .sign_bits(signs),.quality_bits(quality),.generation(generation));
    always @* begin
        bit_value=((dut.group_index*3+dut.lane*5+1)%7)<3;
        // A single wrong measurement must lose the majority and disqualify
        // this comparison (and its group's parity) for enrollment.
        if (dut.group_index==2 && dut.lane==1 && dut.repeat_index==0) bit_value=~bit_value;
        count_a=bit_value ? 40 : 20;
        count_b=bit_value ? 20 : 40;
        if (dut.group_index==4 && dut.lane==3) begin count_a=30; count_b=31; end
        if (mode==1) count_a=0;
        if (mode==2) count_a=65;
        if (mode==3) count_b=count_a;
    end
    always @(posedge clk) if (!rst) begin
        if (enable) enabled_cycles<=enabled_cycles+1;
        if (dut.state==4) begin
            if (enable || clear) $fatal(1,"Counter sampled while running or cleared");
            sample_count<=sample_count+1;
            if (enabled_cycles!=64) $fatal(1,"Incorrect measurement window: %0d",enabled_cycles);
            enabled_cycles<=0;
        end
    end else enabled_cycles<=0;
    task reset_sampler;
        begin
            rst=1; repeat(3) @(negedge clk);
            if (valid || signs!==0 || quality!==0 || generation!==0)
                $fatal(1,"Reset retained volatile response");
            rst=0;
        end
    endtask
    initial begin
        expected=0; expected_quality='1;
        for (g=0;g<16;g=g+1) begin
            for (l=0;l<8;l=l+1) expected[g*9+l]=((g*3+l*5+1)%7)<3;
            expected[g*9+8]=^expected[g*9+:8];
        end
        expected[4*9+3]=0; expected[4*9+8]=^expected[4*9+:8];
        expected_quality[2*9+1]=0; expected_quality[2*9+8]=0;
        expected_quality[4*9+3]=0; expected_quality[4*9+8]=0;
        reset_sampler();
        wait(generation==1); @(negedge clk);
        if (!valid || fault || !done || signs!==expected || quality!==expected_quality)
            $fatal(1,"RO vote/quality/parity failed signs=%h quality=%h",signs,quality);
        if (sample_count!=640) $fatal(1,"Incorrect number of measurements: %0d",sample_count);
        // Publishing must be atomic; the next sweep retains the last vector.
        repeat(500) begin @(negedge clk); if (signs!==expected || !valid) $fatal(1,"Partial refresh published"); end
        wait(generation==2); @(negedge clk);
        if (signs!==expected) $fatal(1,"Continuous resampling changed stable signs");
        reset_sampler(); wait(generation==1); @(negedge clk);
        if (signs!==expected || quality!==expected_quality || !valid) $fatal(1,"Re-enrollment changed signs");
        mode=1; reset_sampler(); wait(done); @(negedge clk);
        if (valid || !fault || quality!==0) $fatal(1,"Stopped oscillator accepted");
        mode=2; reset_sampler(); wait(done); @(negedge clk);
        if (valid || !fault || quality!==0) $fatal(1,"Overfrequency counter accepted");
        mode=0; overflow_b=1; reset_sampler(); wait(done); @(negedge clk);
        if (valid || !fault || quality!==0) $fatal(1,"Overflow counter accepted");
        overflow_b=0; mode=3; reset_sampler(); wait(done); @(negedge clk);
        if (!valid || fault || quality!==0) $fatal(1,"Ties must be ineligible, not hardware faults");
        $display("RO_PUF_ENROLL PASS voting margin parity atomic_refresh reset zero overfrequency overflow tie");
        $finish;
    end
    initial begin #30000000; $fatal(1,"RO sampler watchdog"); end
endmodule
