`timescale 1ns/1ps
module tb_pipeline;
    `include "test_config.vh"
    reg clk=0;
    always #10 clk=~clk; // 50 MHz, matching the existing camera/control fabric.
    reg rst=1, frame_valid=0, result_ready=0;
    reg [143:0] puf_mismatch=144'b0;
    reg puf_signs_valid=1;
    reg [31:0] frame_sequence=0;
    wire frame_ready, frame_consumed, raw_ce, result_valid, timeout_fault, result_expired;
    wire [15:0] raw_address;
    reg [7:0] raw_q;
    wire [31:0] result_sequence, processing_cycles;
    wire signed [31:0] steering_q16, throttle_q16;
    reg [7:0] raw [0:38399];
    reg [7:0] input_expected [0:FRAME_BYTES-1];
    reg [7:0] expected [0:GOLDEN_BYTES-1];
    integer clocks=0, cropped=0, observed=0, released=0;
    integer layer_observed [0:7];
    integer layer, index, e, runs=0, output_file, began, expected_seq;
    integer crop_reads=0, infer_started=0, infer_cycles, layer_last[0:7];
    reg checking=0, test_expire=0;
    string case_name;
    camera_cnn_pipeline #(.MAX_RESULT_HOLD_CYCLES(64),.PUF_ENABLE(1)) dut(.*);

    always @(posedge clk) begin
        clocks=clocks+1;
        if(raw_ce) begin
            if(raw_address>=38400) $fatal(1,"RGB565 address overflow");
            raw_q<=raw[raw_address];
            if(checking) crop_reads=crop_reads+1;
        end
        if(checking) begin
            if(dut.cnn_start) begin
                infer_started=clocks;
                // Refresh after acquisition. This frame must retain the
                // matching generation latched at the inference start.
                puf_mismatch<=~144'b0;
            end
            if(dut.cnn.state!=0 && dut.cnn.frame_puf_mismatch!==144'b0)
                $fatal(1,"PUF refresh contaminated the active inference frame");
            if(dut.cnn_done) infer_cycles=clocks-infer_started;
            if(frame_consumed) begin
                released=released+1;
                if(cropped!=FRAME_BYTES) $fatal(1,"Released incomplete crop");
            end
            if(dut.crop_write) begin
                if(dut.crop_address !== cropped || dut.crop_q !== input_expected[cropped])
                    $fatal(1,"%s crop mismatch byte=%0d address=%0d got=%02x expected=%02x",case_name,cropped,dut.crop_address,dut.crop_q,input_expected[cropped]);
                cropped=cropped+1;
            end
            if(dut.image_ce && dut.image_address>=FRAME_BYTES) $fatal(1,"CNN input address overflow");
            if(dut.cnn.ce[1] && dut.cnn.raddr[1]>=10944) $fatal(1,"Conv1 ring overflow");
            if(dut.cnn.ce[2] && dut.cnn.tail_stage==2 && dut.cnn.raddr[2]>=6912) $fatal(1,"Conv2 ring overflow");
            for(e=0;e<3;e=e+1) if(dut.cnn.valid[e]) begin
                layer=e==2 ? dut.cnn.tail_stage : e;
                index=layer_offset(layer)+dut.cnn.oaddr[e];
                if(dut.cnn.oaddr[e] !== layer_observed[layer]) $fatal(1,"Missing/duplicate layer address");
                if(index>=GOLDEN_BYTES || dut.cnn.oval[e] !== expected[index])
                    $fatal(1,"%s layer=%0d address=%0d got=%0d expected=%0d",case_name,layer,dut.cnn.oaddr[e],dut.cnn.oval[e],$signed(expected[index]));
                layer_observed[layer]=layer_observed[layer]+1;
                layer_last[layer]=clocks-infer_started;
                observed=observed+1;
            end
        end
    end

    task run_case(input string name, input integer steer, input integer throttle);
        integer i, saved_cycles;
        begin
            @(negedge clk);
            if(!frame_ready) $fatal(1,"Not ready between frames");
            puf_mismatch=144'b0;
            case_name=name;
            $readmemh({name,"_raw.mem"},raw);
            $readmemh({name,"_input.mem"},input_expected);
            $readmemh({name,"_expected.mem"},expected);
            cropped=0; observed=0; released=0; crop_reads=0;
            for(i=0;i<8;i=i+1) begin layer_observed[i]=0; layer_last[i]=0; end
            checking=1; began=clocks; expected_seq=runs+100;
            frame_sequence=expected_seq; frame_valid=1;
            @(negedge clk); frame_valid=0;
            // Offer a different sequence while busy. It must not replace the
            // accepted frame, trigger another inference, or mutate the crop.
            repeat(12) @(negedge clk);
            frame_sequence=32'hdeadbeef; frame_valid=1;
            repeat(5) begin @(negedge clk); if(frame_ready) $fatal(1,"Accepted busy frame"); end
            frame_valid=0;
            wait(result_valid);
            @(negedge clk);
            if(timeout_fault || result_sequence!==expected_seq) $fatal(1,"Fault or mixed frame sequence");
            if(observed!=GOLDEN_BYTES || cropped!=FRAME_BYTES || released!=1 || crop_reads!=29640)
                $fatal(1,"Missing bytes or frame ownership release");
            if(steering_q16!==steer || throttle_q16!==throttle) $fatal(1,"Q16 output mismatch");
            if(processing_cycles>=2500000 || clocks-began>=2500000) $fatal(1,"Exceeded 50 ms budget");
            saved_cycles=processing_cycles;
            // Slow consumer: outputs stay stable and camera RAM is already free.
            frame_valid=1;
            repeat(41) begin
                @(negedge clk);
                if(frame_ready || !result_valid || steering_q16!==steer || throttle_q16!==throttle ||
                   result_sequence!==expected_seq || processing_cycles!==saved_cycles || released!=1)
                    $fatal(1,"Result backpressure corrupts data/ownership");
            end
            frame_valid=0;
            if(test_expire) begin
                wait(result_expired); @(negedge clk);
                if(result_valid || !frame_ready || steering_q16!=0 || throttle_q16!=0)
                    $fatal(1,"Unread result failed to expire and release pipeline");
            end else result_ready=1;
            @(negedge clk); result_ready=0; checking=0;
            runs=runs+1;
            $fdisplay(output_file,"%s,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d",
                name,observed,cropped,processing_cycles,infer_cycles,steer,throttle,
                layer_last[0],layer_last[1],layer_last[2],layer_last[3],layer_last[4],layer_last[5],layer_last[6],layer_last[7]);
            $display("PIPELINE PASS %s exact=%0d crop=%0d total_cycles=%0d cnn_cycles=%0d",name,observed,cropped,processing_cycles,infer_cycles);
        end
    endtask

    initial begin
        output_file=$fopen("pipeline_results.csv","w");
        if(!output_file) $fatal(1,"Cannot open results");
        $fdisplay(output_file,"case,exact_layer_bytes,exact_crop_bytes,total_cycles,cnn_cycles,steering_q16,throttle_q16,conv1_last,conv2_last,conv3_last,conv4_last,conv5_last,dense1_last,dense2_last,outputs_last");
        repeat(5) @(negedge clk); rst=0;
        `include "run_cases.vh"
        // Suppress completion to model a hung CNN. Check the real watchdog
        // expires, clears outputs, resets the core, then processes a good frame.
        @(negedge clk); frame_valid=1; frame_sequence=999;
        @(negedge clk); frame_valid=0;
        force dut.cnn_done=1'b0;
        wait(timeout_fault);
        @(negedge clk);
        if(result_valid || steering_q16!=0 || throttle_q16!=0) $fatal(1,"Timeout published stale drive result");
        release dut.cnn_done;
        wait(frame_ready);
        test_expire=1;
        `include "recovery_case.vh"
        test_expire=0;
        `include "recovery_case.vh"
        $display("PIPELINE_ALL PASS frames=%0d watchdog_recovery=1 result_expiry_recovery=1 puf_match_exact=1 refresh_isolated=1",runs);
        $fclose(output_file);
        $finish;
    end
    initial begin #1000000000; $fatal(1,"Simulation watchdog (pipeline stuck)"); end
endmodule
