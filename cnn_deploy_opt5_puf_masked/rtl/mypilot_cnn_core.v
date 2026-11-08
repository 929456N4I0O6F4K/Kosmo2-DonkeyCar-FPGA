`timescale 1ns/1ps
`default_nettype none
// Three concurrent convolution engines, followed by a shared tail engine.
module mypilot_cnn_core #(parameter PUF_ENABLE = 0) (
    input wire clk, rst, start,
    output wire idle, output reg done,
    output wire [15:0] image_address, output wire image_ce,
    input wire [7:0] image_q,
    output reg signed [31:0] steering_q16, throttle_q16,
    input wire [143:0] puf_mismatch,
    input wire puf_signs_valid
);
    localparam IDLE=0, RUN=1, ADVANCE=2, LAUNCH=3, FINISH=4;
    reg [2:0] state, tail_stage;
    reg tail_start;
    wire front_start = start && idle;
    // A periodic RO refresh may finish during inference. Each frame uses one
    // complete volatile generation, including both dense layers.
    reg [143:0] frame_puf_mismatch;
    reg frame_puf_valid;
    always @(posedge clk) begin
        if (rst) begin frame_puf_mismatch<=0; frame_puf_valid<=0; end
        else if (front_start) begin
            frame_puf_mismatch<=puf_mismatch; frame_puf_valid<=puf_signs_valid;
        end
    end
    assign idle = state==IDLE;
    wire [2:0] ce, pce, valid, row_done, engine_done;
    wire [9:0] waddr [0:2];
    wire [6:0] paddr [0:2], row [0:2], col [0:2];
    wire [16:0] raddr [0:2], oaddr [0:2];
    wire signed [7:0] oval [0:2];
    wire [47:0] pq [0:2];
    wire [191:0] w0; wire [255:0] w1; wire [511:0] w2;
    wire [767:0] b0; wire [1023:0] b1; wire [2047:0] b2;
    wire group2;
    wire [7:0] ring0_q, ring1_q, tail_a_q, tail_b_q;
    reg [6:0] produced0, produced1;
    reg finished0, finished1;
    reg [16:0] write0, write1;
    // A granted output row cannot overwrite any consumer's live input row.
    wire ready0 = {1'b0,row[0]} < ({1'b0,row[1]}<<1)+8'd6;
    wire ready1 = {1'b0,produced0} >= ({1'b0,row[1]}<<1)+8'd5 &&
                  {1'b0,row[1]} < ({1'b0,row[2]}<<1)+8'd6;
    wire ready2 = tail_stage!=2 || {1'b0,produced1} >= ({1'b0,row[2]}<<1)+8'd5;
    assign image_ce=ce[0]; assign image_address=raddr[0][15:0];
    mypilot_parameters parameters (
        .clk(clk), .tail_stage(tail_stage), .tail_group(group2),
        .ce0(ce[0]), .pce0(pce[0]), .addr0(waddr[0]), .paddr0(paddr[0]), .w0(w0), .b0(b0), .p0(pq[0]),
        .ce1(ce[1]), .pce1(pce[1]), .addr1(waddr[1]), .paddr1(paddr[1]), .w1(w1), .b1(b1), .p1(pq[1]),
        .ce2(ce[2]), .pce2(pce[2]), .addr2(waddr[2]), .paddr2(paddr[2]), .w2(w2), .b2(b2), .p2(pq[2])
    );
    mypilot_banked_ram #(.BYTES(10944),.BANK_BITS(10),.DISTRIBUTED(1)) conv1_rows (
        .clk(clk), .write_enable(valid[0]), .write_address(write0), .write_data(oval[0]),
        .read_enable(ce[1]), .read_address(raddr[1]), .read_data(ring0_q)
    );
    mypilot_banked_ram #(.BYTES(6912),.BANK_BITS(10),.DISTRIBUTED(1)) conv2_rows (
        .clk(clk), .write_enable(valid[1]), .write_address(write1), .write_data(oval[1]),
        .read_enable(ce[2] && tail_stage==2), .read_address(raddr[2]), .read_data(ring1_q)
    );
    mypilot_banked_ram #(.BYTES(9216)) tail_a (
        .clk(clk), .write_enable(valid[2] && !tail_stage[0]), .write_address(oaddr[2]), .write_data(oval[2]),
        .read_enable(ce[2] && tail_stage[0]), .read_address(raddr[2]), .read_data(tail_a_q)
    );
    mypilot_banked_ram #(.BYTES(6272)) tail_b (
        .clk(clk), .write_enable(valid[2] && tail_stage[0] && tail_stage!=7), .write_address(oaddr[2]), .write_data(oval[2]),
        .read_enable(ce[2] && !tail_stage[0] && tail_stage!=2), .read_address(raddr[2]), .read_data(tail_b_q)
    );
    mypilot_layer_engine #(.LANES(24)) conv1 (
        .clk(clk),.rst(rst),.start(front_start),.pixel_ready(ready0),
        .cfg_taps(11'd75),.cfg_row_span(11'd15),.cfg_row_skip(17'd453),
        .cfg_stride_x(17'd6),.cfg_stride_y(17'd936),.cfg_ring_bytes(17'd0),
        .cfg_out_h(7'd46),.cfg_out_w(7'd76),.cfg_out_c(7'd24),
        .idle(),.done(engine_done[0]),.out_row(row[0]),.out_col(col[0]),.row_done(row_done[0]),
        .input_ce(ce[0]),.input_address(raddr[0]),.input_q(image_q),
        .weight_address(waddr[0]),.weight_q(w0),.bias_q(b0),.channel_group(),
        .parameter_ce(pce[0]),.parameter_address(paddr[0]),.parameter_q(pq[0]),
        .puf_sign_active(1'b0),.puf_mismatch(144'b0),
        .output_valid(valid[0]),.output_value(oval[0]),.output_address(oaddr[0])
    );
    mypilot_layer_engine #(.LANES(32)) conv2 (
        .clk(clk),.rst(rst),.start(front_start),.pixel_ready(ready1),
        .cfg_taps(11'd600),.cfg_row_span(11'd120),.cfg_row_skip(17'd1704),
        .cfg_stride_x(17'd48),.cfg_stride_y(17'd3648),.cfg_ring_bytes(17'd10944),
        .cfg_out_h(7'd21),.cfg_out_w(7'd36),.cfg_out_c(7'd32),
        .idle(),.done(engine_done[1]),.out_row(row[1]),.out_col(col[1]),.row_done(row_done[1]),
        .input_ce(ce[1]),.input_address(raddr[1]),.input_q(ring0_q),
        .weight_address(waddr[1]),.weight_q(w1),.bias_q(b1),.channel_group(),
        .parameter_ce(pce[1]),.parameter_address(paddr[1]),.parameter_q(pq[1]),
        .puf_sign_active(1'b0),.puf_mismatch(144'b0),
        .output_valid(valid[1]),.output_value(oval[1]),.output_address(oaddr[1])
    );
    reg [10:0] cfg_taps,cfg_row_span;
    reg [16:0] cfg_row_skip,cfg_stride_x,cfg_stride_y,cfg_ring_bytes;
    reg [6:0] cfg_out_h,cfg_out_w,cfg_out_c;
    `include "model_config.vh"
    mypilot_layer_engine #(.LANES(64),.PUF_ENABLE(PUF_ENABLE)) tail (
        .clk(clk),.rst(rst),.start(front_start || tail_start),.pixel_ready(ready2),
        .cfg_taps(cfg_taps),.cfg_row_span(cfg_row_span),.cfg_row_skip(cfg_row_skip),
        .cfg_stride_x(cfg_stride_x),.cfg_stride_y(cfg_stride_y),.cfg_ring_bytes(cfg_ring_bytes),
        .cfg_out_h(cfg_out_h),.cfg_out_w(cfg_out_w),.cfg_out_c(cfg_out_c),
        .idle(),.done(engine_done[2]),.out_row(row[2]),.out_col(col[2]),.row_done(row_done[2]),
        .input_ce(ce[2]),.input_address(raddr[2]),
        .input_q(tail_stage==2 ? ring1_q : (tail_stage[0] ? tail_a_q : tail_b_q)),
        .weight_address(waddr[2]),.weight_q(w2),.bias_q(b2),.channel_group(group2),
        .parameter_ce(pce[2]),.parameter_address(paddr[2]),.parameter_q(pq[2]),
        .output_valid(valid[2]),.output_value(oval[2]),.output_address(oaddr[2]),
        .puf_sign_active(frame_puf_valid && (tail_stage==3'd5 || tail_stage==3'd6)),
        .puf_mismatch(frame_puf_mismatch)
    );
    reg signed [63:0] steering_product,throttle_product;
    wire signed [31:0] quant_extended={{24{oval[2][7]}},oval[2]};
    always @(posedge clk) if (valid[2] && tail_stage==7) begin
        if(oaddr[2]==0) steering_product <= (quant_extended-STEERING_ZP)*STEERING_SCALE_Q30;
        if(oaddr[2]==1) throttle_product <= (quant_extended-THROTTLE_ZP)*THROTTLE_SCALE_Q30;
    end
    function signed [31:0] to_q16;
        input signed [63:0] value;
        begin
            if(value>=0) to_q16=(value+64'sd8192)>>>14;
            else to_q16=-(((-value)+64'sd8192)>>>14);
        end
    endfunction
    always @(posedge clk) begin
        if (rst || front_start) begin
            produced0<=0; produced1<=0; write0<=0; write1<=0;
            finished0<=0; finished1<=0;
        end else begin
            if(row_done[0]) produced0<=produced0+1'b1;
            if(row_done[1]) produced1<=produced1+1'b1;
            if(engine_done[0]) finished0<=1;
            if(engine_done[1]) finished1<=1;
            if(valid[0]) write0<=write0==10943 ? 0 : write0+1'b1;
            if(valid[1]) write1<=write1==6911 ? 0 : write1+1'b1;
        end
        if(rst) begin
            state<=IDLE; tail_stage<=2; done<=0; tail_start<=0;
            steering_q16<=0; throttle_q16<=0;
        end else begin
            done<=0; tail_start<=0;
            case(state)
                IDLE: if(start) begin tail_stage<=2; state<=RUN; end
                RUN: if(engine_done[2]) state<=ADVANCE;
                ADVANCE: if(finished0 && finished1) begin
                    if(tail_stage==7) begin
                        steering_q16<=to_q16(steering_product);
                        throttle_q16<=to_q16(throttle_product);
                        state<=FINISH;
                    end else begin tail_stage<=tail_stage+1'b1; state<=LAUNCH; end
                end
                LAUNCH: begin tail_start<=1; state<=RUN; end
                FINISH: begin done<=1; tail_stage<=2; state<=IDLE; end
                default: state<=IDLE;
            endcase
        end
    end
endmodule
`default_nettype wire
