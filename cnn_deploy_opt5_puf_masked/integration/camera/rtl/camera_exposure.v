`timescale 1ns/1ps
`default_nettype none
// Runtime OV2640 sensor AEC/AGC and exposure control, sharing the startup SCCB
// engine. Read/modify/write preserves orientation and unrelated DSP bits.
// setting[31]=automatic; setting[10:0]=sensor exposure units (0..1200).
module camera_exposure #(parameter integer CLOCK_HZ=50000000)(
 input wire clk,reset,enable,valid,input wire [31:0] setting,
 output reg done,output reg [1:0] status,output reg [31:0] applied,
 output reg start,output reg read_en,output reg [7:0] address,data,
 input wire bus_busy,bus_done,input wire [1:0] bus_error,input wire [7:0] read_data
);
 localparam IDLE=0,ISSUE=1,WAIT_BUS=2,RELEASE=3;
 reg [1:0] state;
 reg [4:0] step;
 reg [31:0] requested,age;
 reg [7:0] com8,reg04,reg45,ctrl0;
 wire auto_mode=requested[31];
 wire [7:0] target_com8=(com8&8'hfa)|(auto_mode?8'h05:8'h00);
 wire [7:0] target_ctrl0=auto_mode?(ctrl0&8'hbf):(ctrl0|8'h40);
 reg mismatch;
 always @*begin
  read_en=0;address=8'hff;data=0;mismatch=0;
  case(step)
   0: data=1;
   1:begin read_en=1;address=8'h13;end
   2:begin address=8'h13;data=target_com8;end
   3:begin read_en=1;address=8'h04;end
   4:begin address=8'h04;data=(reg04&8'hfc)|{6'd0,requested[1:0]};end
   5:begin address=8'h10;data=requested[9:2];end
   6:begin read_en=1;address=8'h45;end
   7:begin address=8'h45;data=(reg45&8'hc0)|{5'd0,requested[10]};end
   8:begin read_en=1;address=8'h04;mismatch=read_data!=((reg04&8'hfc)|{6'd0,requested[1:0]});end
   9:begin read_en=1;address=8'h10;mismatch=read_data!=requested[9:2];end
   10:begin read_en=1;address=8'h45;mismatch=read_data!=((reg45&8'hc0)|{5'd0,requested[10]});end
   11:begin read_en=1;address=8'h13;mismatch=(read_data&8'h05)!=(target_com8&8'h05);end
   12: data=0;
   13:begin read_en=1;address=8'hc2;end
   14:begin address=8'hc2;data=target_ctrl0;end
   15:begin read_en=1;address=8'hc2;mismatch=read_data!=target_ctrl0;end
  endcase
 end
 always @(posedge clk)begin
  start<=0;done<=0;
  if(reset)begin
   state<=IDLE;step<=0;requested<=0;age<=0;status<=0;applied<=0;
   com8<=0;reg04<=0;reg45<=0;ctrl0<=0;
  end else begin
   if(state==ISSUE||state==WAIT_BUS)age<=age+1;
   case(state)
    IDLE:if(enable&&valid)begin
     requested<=setting;age<=0;step<=0;status<=0;
     if(setting[30:11]!=0||setting[10:0]>1200)begin status<=2;done<=1;state<=RELEASE;end
     else state<=ISSUE;
    end
    ISSUE:if(!bus_busy)begin start<=1;state<=WAIT_BUS;end
    WAIT_BUS:if(bus_done)begin
     if(bus_error!=0||mismatch)begin status<=3;done<=1;state<=RELEASE;end
     else if(step==15)begin applied<=requested;status<=1;done<=1;state<=RELEASE;end
     else begin
      if(step==1)com8<=read_data;
      if(step==3)reg04<=read_data;
      if(step==6)reg45<=read_data;
      if(step==13)ctrl0<=read_data;
      step<=(step==2&&auto_mode)?11:step+1'b1;state<=ISSUE;
     end
    end
    RELEASE:if(!valid)state<=IDLE;
   endcase
   if((state==ISSUE||state==WAIT_BUS)&&age>=CLOCK_HZ/3)begin status<=3;done<=1;state<=RELEASE;end
  end
 end
endmodule
`default_nettype wire
