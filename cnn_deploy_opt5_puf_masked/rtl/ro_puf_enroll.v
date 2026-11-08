`timescale 1ns/1ps
`default_nettype none

// The physical bank is the previously measured 64 x seven-LUT RO design.
// Only two oscillators run at once. No response is written to nonvolatile storage.
(* syn_hier="hard" *)
module ro_puf_enroll #(
    parameter integer MEASURE_CYCLES = 50000,
    parameter integer REPEAT_COUNT = 9,
    parameter integer MIN_MARGIN = 50,
    parameter integer CONTINUOUS = 1
)(
    input wire clk, rst,
    output wire enroll_done, enroll_fault, signs_valid,
    output wire [143:0] sign_bits, quality_bits,
    output wire [15:0] generation
);
    wire enable, clear, clock_a, clock_b, overflow_a, overflow_b;
    wire [4:0] select_a, select_b;
    wire [23:0] count_a, count_b;
    ro_bank bank(.enable(enable),.select_a(select_a),.select_b(select_b),
                 .clock_a(clock_a),.clock_b(clock_b));
    ro_counter counter_a(.clock_in(clock_a),.clear(clear),.count(count_a),.overflow(overflow_a));
    ro_counter counter_b(.clock_in(clock_b),.clear(clear),.count(count_b),.overflow(overflow_b));
    ro_puf_sampler #(.MEASURE_CYCLES(MEASURE_CYCLES),.REPEAT_COUNT(REPEAT_COUNT),
                     .MIN_MARGIN(MIN_MARGIN),.CONTINUOUS(CONTINUOUS)) sampler(
        .clk(clk),.rst(rst),.count_a(count_a),.count_b(count_b),
        .overflow_a(overflow_a),.overflow_b(overflow_b),
        .enable(enable),.clear(clear),.select_a(select_a),.select_b(select_b),
        .enroll_done(enroll_done),.enroll_fault(enroll_fault),.signs_valid(signs_valid),
        .sign_bits(sign_bits),.quality_bits(quality_bits),.generation(generation));
endmodule

// Count buses are sampled only after the RO bank has stopped and the ripple
// divider has drained. Nine measurements vote on each of 128 comparisons;
// each group adds the parity of its eight voted bits (not an independent bit).
module ro_puf_sampler #(
    parameter integer MEASURE_CYCLES = 50000,
    parameter integer REPEAT_COUNT = 9,
    parameter integer MIN_MARGIN = 50,
    parameter integer CONTINUOUS = 1,
    parameter integer CLEAR_CYCLES = 64,
    parameter integer SETTLE_CYCLES = 32,
    parameter integer DRAIN_CYCLES = 64
)(
    input wire clk, rst,
    input wire [23:0] count_a, count_b,
    input wire overflow_a, overflow_b,
    output wire enable, clear,
    output wire [4:0] select_a, select_b,
    output reg enroll_done, enroll_fault, signs_valid,
    output reg [143:0] sign_bits, quality_bits,
    output reg [15:0] generation
);
    localparam CLEAR=0, SETTLE=1, MEASURE=2, DRAIN=3, SAMPLE=4, COMMIT=5, HOLD=6;
    // 600 MHz engineering bound / 16, with a small edge-count allowance.
    localparam MAX_COUNT = MEASURE_CYCLES * 3 / 4 + 16;
    reg [2:0] state;
    reg [31:0] cycles;
    reg [3:0] group_index;
    reg [2:0] lane;
    reg [7:0] repeat_index, votes;
    reg first_vote, unanimous, margin_ok;
    reg [143:0] working_signs, working_quality;
    reg [7:0] group_signs, group_quality;
    reg [9:0] challenge;
    always @* begin
        case (group_index)
            0:challenge=466;  1:challenge=995;  2:challenge=17;   3:challenge=820;
            4:challenge=676;  5:challenge=699;  6:challenge=393;  7:challenge=555;
            8:challenge=1020; 9:challenge=108; 10:challenge=764; 11:challenge=1016;
           12:challenge=423; 13:challenge=264; 14:challenge=793; 15:challenge=630;
        endcase
    end
    assign select_a = challenge[4:0] + lane * 3;
    assign select_b = challenge[9:5] + lane * 7;
    assign enable = !rst && state == MEASURE;
    assign clear = rst || state == CLEAR;
    wire greater = count_a > count_b;
    wire [23:0] distance = greater ? count_a-count_b : count_b-count_a;
    wire bad_counter = overflow_a || overflow_b || count_a==0 || count_b==0 ||
                       count_a > MAX_COUNT || count_b > MAX_COUNT;
    wire voted = (votes + {7'd0,greater}) > REPEAT_COUNT/2;
    wire eligible = margin_ok && distance >= MIN_MARGIN && unanimous &&
                    (repeat_index==0 || greater==first_vote) && !bad_counter;

    always @(posedge clk) begin
        if (rst) begin
            state<=CLEAR; cycles<=0; group_index<=0; lane<=0; repeat_index<=0;
            votes<=0; first_vote<=0; unanimous<=1; margin_ok<=1;
            working_signs<=0; working_quality<=0; group_signs<=0; group_quality<=0;
            sign_bits<=0; quality_bits<=0; generation<=0;
            enroll_done<=0; enroll_fault<=0; signs_valid<=0;
        end else begin
            case (state)
                CLEAR: if (cycles==CLEAR_CYCLES-1) begin cycles<=0; state<=SETTLE; end
                       else cycles<=cycles+1'b1;
                SETTLE: if (cycles==SETTLE_CYCLES-1) begin cycles<=0; state<=MEASURE; end
                        else cycles<=cycles+1'b1;
                MEASURE: if (cycles==MEASURE_CYCLES-1) begin cycles<=0; state<=DRAIN; end
                         else cycles<=cycles+1'b1;
                DRAIN: if (cycles==DRAIN_CYCLES-1) begin cycles<=0; state<=SAMPLE; end
                       else cycles<=cycles+1'b1;
                SAMPLE: begin
                    if (bad_counter) begin enroll_fault<=1; signs_valid<=0; end
                    if (repeat_index==0) first_vote<=greater;
                    else if (greater!=first_vote) unanimous<=0;
                    if (distance<MIN_MARGIN || bad_counter) margin_ok<=0;
                    if (repeat_index==REPEAT_COUNT-1) begin
                        working_signs[group_index*9+lane]<=voted;
                        working_quality[group_index*9+lane]<=eligible;
                        group_signs[lane]<=voted;
                        group_quality[lane]<=eligible;
                        votes<=0; repeat_index<=0; unanimous<=1; margin_ok<=1;
                        if (lane==7) begin
                            working_signs[group_index*9+8]<=(^group_signs[6:0]) ^ voted;
                            working_quality[group_index*9+8]<=(&group_quality[6:0]) && eligible;
                            lane<=0;
                            if (group_index==15) state<=COMMIT;
                            else begin group_index<=group_index+1'b1; state<=CLEAR; end
                        end else begin lane<=lane+1'b1; state<=CLEAR; end
                    end else begin
                        votes<=votes+{7'd0,greater}; repeat_index<=repeat_index+1'b1; state<=CLEAR;
                    end
                end
                COMMIT: begin
                    sign_bits<=working_signs; quality_bits<=working_quality;
                    generation<=generation+1'b1; enroll_done<=1; signs_valid<=!enroll_fault;
                    group_index<=0; lane<=0;
                    if (CONTINUOUS!=0 && !enroll_fault) state<=CLEAR;
                    else state<=HOLD;
                end
                HOLD: begin end
                default: begin enroll_fault<=1; signs_valid<=0; state<=HOLD; end
            endcase
        end
    end
endmodule
`default_nettype wire
