`timescale 1ns/1ps
module tb_pca_drive;
 reg clk=0;always #5 clk=~clk;
 reg reset=1,stop=1,valid=0;reg [31:0] seq=0,flags=0;reg signed [31:0] angle=0,throttle=0;
 wire ack,ready,fault,active,armed,unconfirmed;wire [63:0] diagnostics;
 reg [31:0] steering=32'h016d01ef; // original 100%: right=365, left=495
 wire [31:0] applied_seq,applied_flags;wire signed [31:0] applied_angle,applied_throttle;
 tri1 scl,sda;reg present=1,hold_sda=0,hold_scl=0;
 pca9685_model model(.present(present),.hold_scl(hold_scl),.hold_sda(hold_sda),.bad_prescale(1'b0),.scl(scl),.sda(sda));
 pca_drive_core #(.CLOCK_HZ(1000000),.BUS_HZ(100000),.ARM_CYCLES(30000),.RETURN_CYCLES(10000),.RETRY_CYCLES(100)) dut(
 .clk(clk),.reset(reset),.stop(stop),.command_valid(valid),.command_sequence(seq),.command_flags(flags),.command_angle(angle),.command_throttle(throttle),.command_ack(ack),
 .command_steering(steering),
 .applied_sequence(applied_seq),.applied_flags(applied_flags),.applied_angle(applied_angle),.applied_throttle(applied_throttle),
 .scl(scl),.sda(sda),.ready(ready),.fault(fault),.active(active),.armed(armed),.shutdown_unconfirmed(unconfirmed),.diagnostics(diagnostics));
 integer i,pairs_before;
 task check_off;
  begin for(i=0;i<16;i=i+1)if(model.registers[9+i*4][4]!==1)$fatal(1,"channel not off %d",i);end
 endtask
 task command(input [31:0] f,input signed [31:0] a,t);
  begin @(negedge clk);seq=seq+1;flags=f;angle=a;throttle=t;valid=1;
   wait(ack);@(negedge clk);valid=0;repeat(3)@(negedge clk);
  end
 endtask
 initial begin
  repeat(5)@(negedge clk);reset=0;wait(ready);check_off;
  if(model.registers[254]!=101)$fatal(1,"not 60Hz");
  command(0,0,0);check_off;stop=0;
  command(0,0,0);
  if(!active||armed||applied_flags!=0||model.registers[8]!=124||model.registers[20]!=172)$fatal(1,"startup neutral missing");
  wait(armed);command(3,-1000000,1000000);
  if({model.registers[9],model.registers[8]}!=441||model.registers[20]!=239||applied_angle!=-1000000||applied_throttle!=1000000)$fatal(1,"left/full forward PWM mapping");
  command(1,0,430000);
  if({model.registers[9],model.registers[8]}!=406)$fatal(1,"historical low PWM mapping");
  command(1,0,500000);
  if({model.registers[9],model.registers[8]}!=411)$fatal(1,"half throttle rounding");
  command(1,0,999999);
  if({model.registers[9],model.registers[8]}!=441)$fatal(1,"near full throttle rounding");
  steering=32'h016701f6; // 110% default: right=359, left=502
  command(1,-1000000,0);
  if({model.registers[21],model.registers[20]}!=502)$fatal(1,"default left expansion");
  command(1,1000000,0);
  if({model.registers[21],model.registers[20]}!=359)$fatal(1,"default right expansion");
  steering=32'h018c0211; // independent 150% left / 50% right
  pairs_before=model.pair_writes;
  command(1,-1000000,0);
  if({model.registers[21],model.registers[20]}!=529||applied_angle!=-1000000)$fatal(1,"extended left high byte or label");
  if(model.pair_writes!=pairs_before+2||model.registers[0]!=8'h20||model.registers[1][3]!=0)$fatal(1,"PWM pair must commit in one STOP transaction");
  command(1,1000000,0);
  if({model.registers[21],model.registers[20]}!=396)$fatal(1,"independent right span");
  command(0,0,0);command(0,0,0);
  if({model.registers[21],model.registers[20]}!=428||!armed||fault)$fatal(1,"extended endpoint return to neutral");
  steering=32'h014d01ce; // independent 50% left / 150% right
  command(1,-1000000,0);
  if({model.registers[21],model.registers[20]}!=462)$fatal(1,"minimum left span");
  command(1,1000000,0);
  if({model.registers[21],model.registers[20]}!=333)$fatal(1,"maximum right span");
  steering=32'h016d01ef;
  command(3,1000000,0);
  if(model.registers[8]!=124||model.registers[20]!=109)$fatal(1,"right mapping");
  command(0,0,0);
  if(applied_flags!=0||model.registers[8]!=124||model.registers[20]!=172)$fatal(1,"commanded stop not neutral");
  if(!armed||!active||unconfirmed)$fatal(1,"ordinary stop discarded neutral standby");
  command(1,-10000,1000000);
  if(!armed||applied_throttle!=1000000||model.registers[8]!=185||model.registers[20]!=173)$fatal(1,"restart delayed or fine left steering lost");
  command(1,10000,0);
  if(model.registers[20]!=171)$fatal(1,"fine right steering lost");
  command(0,0,0);command(1,0,1000000);
  if(!armed||applied_throttle!=1000000)$fatal(1,"repeated stop/start delayed");
  stop=1;wait(dut.returning);wait(!active&&!unconfirmed);check_off;
  if(applied_flags!=0)$fatal(1,"watchdog stop label still enabled");
  // Returning from a timeout cannot replay a stale high command.
  stop=0;repeat(300)@(negedge clk);check_off;
  command(1,0,1000000);wait(armed);command(1,0,1000000);
  present=0;@(negedge clk);seq=seq+1;valid=1;angle=100000;wait(fault);
  if(applied_flags!=0||!unconfirmed)$fatal(1,"bus failure not latched");
  present=1;valid=0;wait(!unconfirmed);check_off;
  if(ready)$fatal(1,"fault auto-rearmed");
  // The PCA can lose power while no user is driving. Disabled heartbeats
  // must detect absence, and also a silent reset of its PWM configuration.
  @(negedge clk);reset=1;repeat(5)@(negedge clk);reset=0;wait(ready);
  command(0,0,0);wait(armed);command(0,0,0);
  present=0;@(negedge clk);seq=seq+1;flags=0;valid=1;wait(fault);
  if(armed||ready||!unconfirmed)$fatal(1,"standby power loss invisible");
  present=1;valid=0;wait(!unconfirmed);check_off;
  @(negedge clk);reset=1;repeat(5)@(negedge clk);reset=0;wait(ready);
  command(0,0,0);wait(armed);command(0,0,0);
  model.registers[254]=30;
  @(negedge clk);seq=seq+1;flags=0;valid=1;wait(fault);
  valid=0;wait(!unconfirmed);check_off;
  if(armed||ready)$fatal(1,"standby frequency reset invisible");
  @(negedge clk);reset=1;repeat(5)@(negedge clk);reset=0;wait(ready);
  command(0,0,0);wait(armed);command(1,0,1000000);
  @(negedge clk);seq=seq+1;throttle=1000001;valid=1;wait(fault);
  valid=0;wait(!active&&!unconfirmed);check_off;
  if(applied_flags!=0||applied_throttle!=0)$fatal(1,"out of range throttle not stopped");
  @(negedge clk);reset=1;repeat(5)@(negedge clk);reset=0;wait(ready);
  command(0,0,0);wait(armed);command(1,-1000000,0);
  @(negedge clk);seq=seq+1;steering=32'h016d0212;valid=1;wait(fault);
  valid=0;wait(!active&&!unconfirmed);check_off;
  if(applied_flags!=0)$fatal(1,"unsafe steering endpoint not stopped");
  $display("ALL CONTINUOUS PCA DRIVE TESTS PASS");$finish;
 end
 initial begin #10000000;$fatal(1,"drive test timeout");end
endmodule
