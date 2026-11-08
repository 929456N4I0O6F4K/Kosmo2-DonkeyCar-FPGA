`timescale 1ns/1ps
`default_nettype none

module puf_auto_enroll #(
    parameter integer N = 128,
    parameter integer K = 8,
    parameter integer NUM_CHAL = 16,
    parameter integer REPEAT_COUNT = 5,
    parameter integer TIMEOUT_CYCLES = 100000
) (
    input wire clk,
    input wire rst,
    output reg puf_trigger,
    output reg [N-1:0] puf_challenge,
    input wire puf_ready,
    input wire [K-1:0] puf_response,
    input wire puf_xor,
    output reg enroll_done,
    output reg enroll_fault,
    output reg signs_valid,
    output reg [143:0] sign_bits
);
    localparam IDLE = 3'd0, LOAD_CHAL = 3'd1, TRIG = 3'd2,
               WAIT_RDY = 3'd3, RELEASE = 3'd4, SAMPLE = 3'd5,
               DONE = 3'd6;

    reg [N-1:0] challenge_rom [0:NUM_CHAL-1];
    initial begin
        challenge_rom[0]  = 128'he068aca61a48b8bc34d2f4e5bba58f24;
        challenge_rom[1]  = 128'hd9cb7845045b4398b837b71f554aa281;
        challenge_rom[2]  = 128'h217bbe004b4f22efc6ae9394677b7701;
        challenge_rom[3]  = 128'hf453ddd1b70ca1c472b56c148f312728;
        challenge_rom[4]  = 128'h1d32bc5c0ff57bf60a3effae28c92dbe;
        challenge_rom[5]  = 128'h7edf4fb5bb1d3f6947697bd503404df8;
        challenge_rom[6]  = 128'h2a313462b891add9a6ec4c9c74ec3c9a;
        challenge_rom[7]  = 128'h8e828314505dd14834312657d741d3e1;
        challenge_rom[8]  = 128'h2922ad7724e4cd204d4853c02612d40c;
        challenge_rom[9]  = 128'h1f8b6192552a41c2ce3aa35c02962f13;
        challenge_rom[10] = 128'h555ccd88d9c8071ce97df7df2609722d;
        challenge_rom[11] = 128'h9c9adad88e36b445bc574aca3581f92d;
        challenge_rom[12] = 128'h89a74dc0c0c9e4ce10f0c75fa4edb061;
        challenge_rom[13] = 128'h2abc42993db04e459309e4659df07bbb;
        challenge_rom[14] = 128'h68269d84bd3ffb515e69ffeb7e5ba57b;
        challenge_rom[15] = 128'hbc6f7c64073b087ddb302cc44656abf4;
    end

    (* ASYNC_REG = "TRUE" *) reg puf_rdy_s1, puf_rdy_s2;
    always @(posedge clk) begin
        puf_rdy_s1 <= puf_ready;
        puf_rdy_s2 <= puf_rdy_s1;
    end

    reg [2:0] state;
    reg [4:0] chal_idx;
    reg [7:0] repeat_idx;
    reg [19:0] timeout_cnt;
    reg [3:0] release_cnt;
    reg [8:0] resp_buf;
    reg [3:0] vote_count [0:8];
    integer i;

    always @(posedge clk) begin
        if (rst) begin
            state <= IDLE;
            puf_trigger <= 0;
            puf_challenge <= 0;
            enroll_done <= 0;
            enroll_fault <= 0;
            signs_valid <= 0;
            sign_bits <= 0;
            chal_idx <= 0;
            repeat_idx <= 0;
            timeout_cnt <= 0;
            release_cnt <= 0;
            resp_buf <= 0;
            for (i = 0; i < 9; i = i + 1)
                vote_count[i] <= 0;
        end else begin
            puf_trigger <= 0;
            case (state)
                IDLE: begin
                    chal_idx <= 0;
                    repeat_idx <= 0;
                    enroll_done <= 0;
                    enroll_fault <= 0;
                    signs_valid <= 0;
                    sign_bits <= 0;
                    state <= LOAD_CHAL;
                end
                LOAD_CHAL: begin
                    puf_challenge <= challenge_rom[chal_idx];
                    state <= TRIG;
                end
                TRIG: begin
                    puf_trigger <= 1;
                    state <= WAIT_RDY;
                end
                WAIT_RDY: begin
                    puf_trigger <= 1;
                    timeout_cnt <= timeout_cnt + 1'b1;
                    if (puf_rdy_s2) begin
                        resp_buf <= {puf_xor, puf_response};
                        puf_trigger <= 0;
                        timeout_cnt <= 0;
                        release_cnt <= 0;
                        state <= RELEASE;
                    end else if (timeout_cnt >= TIMEOUT_CYCLES) begin
                        resp_buf <= 0;
                        puf_trigger <= 0;
                        timeout_cnt <= 0;
                        release_cnt <= 0;
                        enroll_fault <= 1;
                        state <= RELEASE;
                    end
                end
                RELEASE: begin
                    if (release_cnt == 10) begin
                        release_cnt <= 0;
                        state <= SAMPLE;
                    end else begin
                        release_cnt <= release_cnt + 1'b1;
                    end
                end
                SAMPLE: begin
                    for (i = 0; i < 9; i = i + 1)
                        if (resp_buf[i])
                            vote_count[i] <= vote_count[i] + 1'b1;
                    if (repeat_idx == REPEAT_COUNT - 1) begin
                        for (i = 0; i < 9; i = i + 1) begin
                            sign_bits[chal_idx*9+i] <=
                                (vote_count[i] + resp_buf[i]) > (REPEAT_COUNT / 2);
                            vote_count[i] <= 0;
                        end
                        repeat_idx <= 0;
                        if (chal_idx == NUM_CHAL - 1) begin
                            enroll_done <= 1;
                            signs_valid <= !enroll_fault;
                            state <= DONE;
                        end else begin
                            chal_idx <= chal_idx + 1'b1;
                            state <= LOAD_CHAL;
                        end
                    end else begin
                        repeat_idx <= repeat_idx + 1'b1;
                        state <= LOAD_CHAL;
                    end
                end
                DONE: begin
                    enroll_done <= 1;
                    signs_valid <= !enroll_fault;
                end
                default: state <= IDLE;
            endcase
        end
    end
endmodule

`default_nettype wire
