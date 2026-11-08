`default_nettype none
// Seven native LUT stages: enabled NAND followed by six inverters.
// Position constraints and post-route checks are part of this implementation.
(* syn_hier="hard" *)
module ro_cell(input wire enable, output wire clock_out);
 (* syn_keep=1 *) wire [6:0] chain;
 GTP_LUT4 #(.INIT(16'h7777)) gate0(.I0(chain[6]),.I1(enable),.I2(1'b0),.I3(1'b0),.Z(chain[0])) /* synthesis syn_noprune=1 */;
 GTP_LUT4 #(.INIT(16'h5555)) inv1(.I0(chain[0]),.I1(1'b0),.I2(1'b0),.I3(1'b0),.Z(chain[1])) /* synthesis syn_noprune=1 */;
 GTP_LUT4 #(.INIT(16'h5555)) inv2(.I0(chain[1]),.I1(1'b0),.I2(1'b0),.I3(1'b0),.Z(chain[2])) /* synthesis syn_noprune=1 */;
 GTP_LUT4 #(.INIT(16'h5555)) inv3(.I0(chain[2]),.I1(1'b0),.I2(1'b0),.I3(1'b0),.Z(chain[3])) /* synthesis syn_noprune=1 */;
 GTP_LUT4 #(.INIT(16'h5555)) inv4(.I0(chain[3]),.I1(1'b0),.I2(1'b0),.I3(1'b0),.Z(chain[4])) /* synthesis syn_noprune=1 */;
 GTP_LUT4 #(.INIT(16'h5555)) inv5(.I0(chain[4]),.I1(1'b0),.I2(1'b0),.I3(1'b0),.Z(chain[5])) /* synthesis syn_noprune=1 */;
 GTP_LUT4 #(.INIT(16'h5555)) inv6(.I0(chain[5]),.I1(1'b0),.I2(1'b0),.I3(1'b0),.Z(chain[6])) /* synthesis syn_noprune=1 */;
 assign clock_out=chain[6];
endmodule
`default_nettype wire
