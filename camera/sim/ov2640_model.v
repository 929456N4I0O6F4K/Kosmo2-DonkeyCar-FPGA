`timescale 1ns/1ps
// Behavioral SCCB model; verifies wire-level addressing, STOP reads and writes.
module ov2640_model(input wire present, bad_id, hold_scl, inout wire scl,sda);
 reg drive_low=0, active=0, selected=0, reading=0;
 reg [7:0] shift=0, pointer=0, bank=0, tx_byte=0;
 reg [7:0] registers[0:511];
 integer bits=0, phase=0, writes=0, i;
 assign sda=drive_low ? 1'b0 : 1'bz;
 assign scl=hold_scl ? 1'b0 : 1'bz;
 initial for(i=0;i<512;i=i+1) registers[i]=0;
 always @(negedge sda) if(scl===1'b1) begin
  active=1; selected=0; reading=0; bits=0; phase=0; shift=0;
 end
 always @(posedge sda) if(scl===1'b1) begin active=0; drive_low=0; end
 always @(posedge scl) if(active) begin
  if(reading) begin
   if(bits<8) bits=bits+1;
   else begin
    if(sda!==1'b1) $fatal(1,"Master did not NACK final read byte");
    active=0;
   end
  end else if(bits<8) begin
   shift={shift[6:0],sda}; bits=bits+1;
   if(bits==8 && phase==0) selected=present && shift[7:1]==7'h30;
  end else begin
   bits=0;
   if(selected) begin
    if(phase==0) begin
     if(shift[0]) begin
      reading=1;
      if(bank==1 && pointer==8'h0a) tx_byte=bad_id ? 8'h77 : 8'h26;
      else if(bank==1 && pointer==8'h0b) tx_byte=8'h42;
      else tx_byte=registers[{bank[0],pointer}];
     end else phase=1;
    end else if(phase==1) begin pointer=shift; phase=2; end
    else begin
     if(pointer==8'hff) bank=shift;
     else registers[{bank[0],pointer}]=shift;
     writes=writes+1;
    end
   end
  end
 end
 always @(negedge scl) begin
  #1;
  if(!active) drive_low=0;
  else if(reading) drive_low=(bits<8) ? !tx_byte[7-bits] : 0;
  else drive_low=(bits==8 && selected);
 end
endmodule

