// Generated from the deployed TFLite.
`default_nettype none
module mypilot_parameters(
    input wire clk,
    input wire [2:0] tail_stage,
    input wire tail_group,
    input wire ce0, pce0,
    input wire [9:0] addr0,
    input wire [6:0] paddr0,
    output wire [191:0] w0,
    output wire [767:0] b0,
    output reg [47:0] p0,
    input wire ce1, pce1,
    input wire [9:0] addr1,
    input wire [6:0] paddr1,
    output wire [255:0] w1,
    output wire [1023:0] b1,
    output reg [47:0] p1,
    input wire ce2, pce2,
    input wire [9:0] addr2,
    input wire [6:0] paddr2,
    output wire [511:0] w2,
    output wire [2047:0] b2,
    output reg [47:0] p2
);
    (* rom_style="distributed", syn_romstyle="logic" *) reg [191:0] wmem0 [0:74];
    (* rom_style="distributed", syn_romstyle="logic" *) reg [47:0] pmem0 [0:23];
    reg [191:0] wq0;
    localparam [767:0] B0 = 768'hffffdcf6ffffe2b9ffffe42a00001525ffff9899000009bd0000003bffffceae000006ac00000913ffffca2f000021e90000121a0000004fffff9609000010e5fffffcc2000016c0ffffba6800000bd5fffffc14ffffd3f6ffffceaefffff8a8;
    initial begin $readmemh("stage0_weights.mem",wmem0); $readmemh("stage0_requant.mem",pmem0); end
    always @(posedge clk) if (ce0) wq0 <= wmem0[addr0];
    assign w0=wq0; assign b0=B0;
    always @(posedge clk) if(pce0) p0 <= pmem0[paddr0];
    (* rom_style="block", syn_romstyle="block_rom" *) reg [255:0] wmem1 [0:599];
    (* rom_style="distributed", syn_romstyle="logic" *) reg [47:0] pmem1 [0:31];
    reg [255:0] wq1;
    localparam [1023:0] B1 = 1024'h00000db1000003bbffffeb240000012a000002b4ffffee9d00000659000002b200000397fffffb5400000160000001dffffffe19fffffab5fffff7dd00000630fffff4c90000009afffffc28ffffff9cfffff05e0000007b000000d6ffffef44ffffffe3fffff3c4fffffd3a0000047800000293000007af000001720000003a;
    initial begin $readmemh("stage1_weights.mem",wmem1); $readmemh("stage1_requant.mem",pmem1); end
    always @(posedge clk) if (ce1) wq1 <= wmem1[addr1];
    assign w1=wq1; assign b1=B1;
    always @(posedge clk) if(pce1) p1 <= pmem1[paddr1];
    (* rom_style="block", syn_romstyle="block_rom" *) reg [511:0] wmem2 [0:799];
    (* rom_style="distributed", syn_romstyle="logic" *) reg [47:0] pmem2 [0:63];
    reg [511:0] wq2;
    localparam [2047:0] B2 = 2048'hfffffb4f000008a900000560000006fefffffa65000004e20000076700000e0500000aaf00000997ffffbab1ffffe3750000086f0000032effffe383ffffdbdf000008b300000a0effffe1de00000118ffffea74fffff52e00000368fffffa0efffff3b700000d6efffffd610000005600001951fffffdc2ffffcffeffffff3f000008cbffffe5f70000120c0000174f000001b1000004c1000009ea0000066700000f9b000011a7ffffffd80000045affffcd2200000d98fffffc6900000277ffffee3cfffff214ffffe93cffffe7ddffffea01ffffec8ffffff5d6000003b00000169700000bc0fffff426fffffb1600000fc7fffffa11fffffd820000002e;
    initial begin $readmemh("stage2_weights.mem",wmem2); $readmemh("stage2_requant.mem",pmem2); end
    always @(posedge clk) if (ce2 && tail_stage==3'd2) wq2 <= wmem2[addr2];
    (* rom_style="block", syn_romstyle="block_rom" *) reg [511:0] wmem3 [0:575];
    (* rom_style="distributed", syn_romstyle="logic" *) reg [47:0] pmem3 [0:63];
    reg [511:0] wq3;
    localparam [2047:0] B3 = 2048'h00000b44000005ca000006abffffe4440000220efffff641fffff8ed0000099f00000fe3000008b3000018dfffffeebc0000076400000f460000102f0000001300000c85ffffc7a200000d60fffff4f000000ad600000cbe0000051800002b89fffff5d80000000c00000c0200000ee200000961fffff5c9000024e7000005e70000075e0000162300000e16ffffe8ae00000853fffffd950000097d00001741000004980000055200000f860000081bffffde0fffffec7cfffffe84000004c9fffffd9100001f9100000188fffffdafffffdc06000014df00000f3400000f5a000013c9000005d2ffffb4d3fffffb1cfffffcab0000061cffffb2be00000ba4;
    initial begin $readmemh("stage3_weights.mem",wmem3); $readmemh("stage3_requant.mem",pmem3); end
    always @(posedge clk) if (ce2 && tail_stage==3'd3) wq3 <= wmem3[addr2];
    (* rom_style="block", syn_romstyle="block_rom" *) reg [127:0] wmem4 [0:575];
    (* rom_style="distributed", syn_romstyle="logic" *) reg [47:0] pmem4 [0:15];
    reg [127:0] wq4;
    localparam [511:0] B4 = 512'hfffff1a1000011c4000014ad00000bab00001f9c00001418ffffeeb300000c2d00000f4a0000157c00000550ffffa2b100001cf100001f1300001ea100000421;
    initial begin $readmemh("stage4_weights.mem",wmem4); $readmemh("stage4_requant.mem",pmem4); end
    always @(posedge clk) if (ce2 && tail_stage==3'd4) wq4 <= wmem4[addr2];
    (* rom_style="block", syn_romstyle="block_rom" *) reg [799:0] wmem5 [0:959];
    (* rom_style="distributed", syn_romstyle="logic" *) reg [47:0] pmem5 [0:99];
    reg [799:0] wq5;
    localparam [3199:0] B5 = 3200'h00001853000037440000152c000027b6000040b5000007630000048c00002c27000025a4ffff9f7a00002532ffffbcc100006c90000015f700002b2500002cf7000046f5000020ee0000099a00002aa600003c6600004f5600003add00002665ffffeb740000348800006c11ffffde800000053700001d5000003d26000038b6000028370000047bffffe52bffffa7b9ffffe53e00002d84ffffe3aa00003d8c00000c9500000078000037a800002c5dffffe410000035cc0000371000002ab7ffffd68e0000133dffff971e00001bcd000020f300002f60ffff9731000005f800002d670000032dffff340a00002d5e000010b600005d1200002fbd0000258cfffff1af0000349f0000100a00004c2400003a6e000036030000178c00002f1300002de2000010e400003a600000289e00002dfe00001b21ffffeb83ffffb9d70000238f00001ee9000043adffffeaa9ffffe1fc000040c000003c84ffff3ef10000138f00001eee0000383ffffff9c300004e62000022d9fffff2d40000503b00002d700000335d00007670000057ea;
    initial begin $readmemh("stage5_weights.mem",wmem5); $readmemh("stage5_requant.mem",pmem5); end
    always @(posedge clk) if (ce2 && tail_stage==3'd5) wq5 <= wmem5[addr2];
    (* rom_style="distributed", syn_romstyle="logic" *) reg [399:0] wmem6 [0:99];
    (* rom_style="distributed", syn_romstyle="logic" *) reg [47:0] pmem6 [0:49];
    reg [399:0] wq6;
    localparam [1599:0] B6 = 1600'h0000295b000039b7000032da0000561c00005773000043c800002bff0000457b00003e97000059a10000208b0000453d00004c54ffff1bf200005a1200003225ffffb08d00003e3d00003925ffff625400004dd200002ba7000001cd00004bcb000029e20000335b00002f2d000043a600004aaa00005bdc00001cd700003f0100003ce70000364f000054da00002b6d0000301d00004e21000048f000004d9b00002b8d00002ca90000595d00004c39000037a600003d2f000055da0000316e00003fba00002928;
    initial begin $readmemh("stage6_weights.mem",wmem6); $readmemh("stage6_requant.mem",pmem6); end
    always @(posedge clk) if (ce2 && tail_stage==3'd6) wq6 <= wmem6[addr2];
    (* rom_style="distributed", syn_romstyle="logic" *) reg [15:0] wmem7 [0:49];
    (* rom_style="distributed", syn_romstyle="logic" *) reg [47:0] pmem7 [0:1];
    reg [15:0] wq7;
    localparam [63:0] B7 = 64'h0006712affffeff0;
    initial begin $readmemh("stage7_weights.mem",wmem7); $readmemh("stage7_requant.mem",pmem7); end
    always @(posedge clk) if (ce2 && tail_stage==3'd7) wq7 <= wmem7[addr2];
    reg [511:0] tail_w; reg [2047:0] tail_b;
    assign w2=tail_w; assign b2=tail_b;
    always @* begin
        tail_w=0; tail_b=0;
        case(tail_stage)
            3'd2: begin tail_w=wq2; tail_b=B2; end
            3'd3: begin tail_w=wq3; tail_b=B3; end
            3'd4: begin tail_w=wq4; tail_b=B4; end
            3'd5: begin tail_w=tail_group ? {224'b0,wq5[799:512]} : wq5[511:0]; tail_b=tail_group ? {896'b0,B5[3199:2048]} : B5[2047:0]; end
            3'd6: begin tail_w=wq6; tail_b=B6; end
            3'd7: begin tail_w=wq7; tail_b=B7; end
        endcase
    end
    always @(posedge clk) if(pce2) begin
        case(tail_stage)
            3'd2: p2 <= pmem2[paddr2];
            3'd3: p2 <= pmem3[paddr2];
            3'd4: p2 <= pmem4[paddr2];
            3'd5: p2 <= pmem5[paddr2];
            3'd6: p2 <= pmem6[paddr2];
            3'd7: p2 <= pmem7[paddr2];
            default: p2 <= 0;
        endcase
    end
endmodule
`default_nettype wire
