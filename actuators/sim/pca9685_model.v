`timescale 1ns/1ps
// Wire-level model: address, ACK/NACK, pointer, individual and broadcast writes.
// Does not model oscillator tolerance or electrical rise times.
module pca9685_model(input wire present,hold_scl,hold_sda,bad_prescale,
 inout wire scl,sda);
 reg drive_low=0,active=0,selected=0,reading=0;
 reg [7:0] shift=0,pointer=0,tx_byte=0;
 reg [7:0] registers[0:255];
 integer bits=0,phase=0,writes=0,i,j;
 integer transaction_bytes=0,transaction_pointer=0,pair_writes=0;
 assign sda=(drive_low || hold_sda) ? 1'b0 : 1'bz;
 assign scl=hold_scl ? 1'b0 : 1'bz;
 initial begin
  for(i=0;i<256;i=i+1) registers[i]=0;
  registers[0]=8'h11; registers[1]=4; registers[254]=8'h1e;
  for(i=0;i<16;i=i+1) registers[9+4*i]=8'h10;
 end
 always @(negedge sda) if(scl===1'b1) begin
  active=1; selected=0; reading=0; bits=0; phase=0; shift=0;
  transaction_bytes=0;
 end
 always @(posedge sda) if(scl===1'b1) begin
  if(transaction_bytes==2 && (transaction_pointer==8 || transaction_pointer==20))pair_writes=pair_writes+1;
  active=0; drive_low=0;
 end
 always @(posedge scl) if(active) begin
  if(reading) begin
   if(bits<8) bits=bits+1;
   else begin
    if(sda!==1'b1) $fatal(1,"Master must NACK last read byte");
    active=0;
   end
  end else if(bits<8) begin
   shift={shift[6:0],sda}; bits=bits+1;
   if(bits==8 && phase==0) selected=present && shift[7:1]==7'h40;
  end else begin
   bits=0;
   if(selected) begin
    if(phase==0) begin
     if(shift[0]) begin
      reading=1;
      tx_byte=(pointer>=250 && pointer<=253) ? 0 : registers[pointer];
      if(pointer==254 && bad_prescale) tx_byte=8'h1e;
     end else phase=1;
    end else if(phase==1) begin pointer=shift;transaction_pointer=shift; phase=2; end
    else begin
     if(pointer==254 && !registers[0][4]) $fatal(1,"PRE_SCALE written outside sleep");
     if(pointer>=250 && pointer<=253) begin
      for(j=0;j<16;j=j+1) registers[6+4*j+pointer-250]=shift;
     end else registers[pointer]=shift;
     writes=writes+1;
     transaction_bytes=transaction_bytes+1;
     if(registers[0][5])pointer=pointer+1;
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
