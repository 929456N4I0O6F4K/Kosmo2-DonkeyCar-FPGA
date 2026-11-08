`timescale 1ns/1ps
// Key images and expected values come from tools/simulate.py (puf_key_image.py).
module tb_puf_key_store;
    `include "key_fixture.vh"
    reg clk=0;
    always #10 clk=~clk;
    reg rst=1;
    reg [143:0] signs=0;
    wire [2:0] loaded, capture, drive;
    wire [143:0] mismatch [0:2];
    puf_key_store #(.KEY_FILE("key_drive.mem")) drive_key(.clk(clk),.rst(rst),.signs(signs),
        .loaded(loaded[0]),.capture_enable(capture[0]),.drive_enable(drive[0]),.mismatch(mismatch[0]));
    puf_key_store #(.KEY_FILE("key_capture.mem")) capture_key(.clk(clk),.rst(rst),.signs(signs),
        .loaded(loaded[1]),.capture_enable(capture[1]),.drive_enable(drive[1]),.mismatch(mismatch[1]));
    puf_key_store #(.KEY_FILE("key_bad.mem")) bad_key(.clk(clk),.rst(rst),.signs(signs),
        .loaded(loaded[2]),.capture_enable(capture[2]),.drive_enable(drive[2]),.mismatch(mismatch[2]));
    integer i, cycles;

    task check_loaded;
        begin
            if (loaded!==3'b111) $fatal(1,"Key ROM did not finish loading");
            if (drive!==3'b001 || capture!==3'b010) $fatal(1,"Mode decode drive=%b capture=%b",drive,capture);
            for (i=0;i<4;i=i+1) begin
                signs = i==0 ? TEST_BINDING : i==1 ? ~TEST_BINDING : {$random,$random,$random,$random,$random};
                #1;
                if (i==0 && mismatch[0]!==0) $fatal(1,"Enrolled vector altered opt4");
                if (i==1 && mismatch[0]!==TEST_SIGN_MASK) $fatal(1,"Inverted vector missed stable bits");
                if (mismatch[0]!==(TEST_SIGN_MASK & (signs ^ TEST_BINDING)))
                    $fatal(1,"Production mismatch wrong for vector %0d",i);
                if (mismatch[1]!==0 || mismatch[2]!==0)
                    $fatal(1,"Capture or invalid key produced a mismatch");
            end
        end
    endtask

    initial begin
        repeat(3) @(negedge clk);
        rst=0;
        cycles=0;
        while (loaded!==3'b111 && cycles<40) begin
            if (drive!==0 || capture!==0) $fatal(1,"Mode active before the key finished loading");
            @(negedge clk); cycles=cycles+1;
        end
        check_loaded();
        // A JTAG/debug reset must clear and reload the key.
        rst=1; @(negedge clk);
        if (loaded!==0 || drive!==0 || capture!==0 || mismatch[0]!==0) $fatal(1,"Reset did not clear the key");
        rst=0;
        repeat(40) @(negedge clk);
        check_loaded();
        $display("PUF_KEY_STORE PASS load_cycles=%0d drive=masked capture=no_binding invalid=stopped reload=ok",cycles);
        $finish;
    end
    initial begin #100000; $fatal(1,"Key store watchdog"); end
endmodule
