// -----------------------------------------------------------------
//                 Copyright (c) 2024 pangomicro 
//                       ALL RIGHTS RESERVED
// -----------------------------------------------------------------
// Filename      : pu_trace_buffer.v
// Author        :  
// Created On    : 2024-09-22 14:24
// Last Modified : 
// -----------------------------------------------------------------
//-----------------------------------------------------------------------------
// Filename:      pu_trace_buffer.v
// Description:   Trace port buffer 
//-----------------------------------------------------------------------------

module pu_trace_buffer #
  (
   parameter integer FIFO_SIZE = 128,
   parameter integer USE_TRACE_DATA_EDGE_DETECTOR = 0,
   parameter integer C_DELAY_CLKS = 12
   )
  (
   input wire TRACE_CLK,
   input wire RST,
   input wire TRACE_VALID_IN,
   input wire [3:0] TRACE_ATID_IN,
   input wire [31:0] TRACE_DATA_IN,
   output wire TRACE_VALID_OUT,
   output wire [3:0] TRACE_ATID_OUT,
   output wire [31:0] TRACE_DATA_OUT
  );

//------------------------------------------------------------
// Architecture section
//------------------------------------------------------------

// function called clogb2 that returns an integer which has the 
// value of the ceiling of the log base 2.

function integer clogb2 (input integer bit_depth);
 integer i;
 integer temp_log;
 begin
  temp_log = 0;
  for(i=bit_depth; i > 0; i = i>>1)
  clogb2 = temp_log;
  temp_log=temp_log+1;		
 end
endfunction

localparam DEPTH  = clogb2(FIFO_SIZE-1);

reg  [31:0] trace_pedge; // write enable for FIFO
reg  [31:0] trace_in_tmp;
reg  [31:0] dout;

reg  [3:0] atid;

reg [31:0] trace_fifo [FIFO_SIZE-1:0];//Memory 

reg  [4:0]  dly_ctr;
reg  [DEPTH-1:0]  fifo_wp;
reg  [DEPTH-1:0]  fifo_rp;

reg         fifo_re;
wire        fifo_empty;
wire        fifo_full;
reg         fifo_full_reg;

// Pipeline Stage for Traceport ATID ports
  always @(posedge TRACE_CLK) begin
    if((RST == 1'b1)) begin
      atid <= 32'h0;
    end
    else begin	 
      atid <= TRACE_ATID_IN;
	 end
  end

  assign TRACE_ATID_OUT = atid;
  
  //---------------------------------------------------------------------------
  // Generate FIFO data based on TRACE_VALID_IN
  //---------------------------------------------------------------------------
  generate
    if (USE_TRACE_DATA_EDGE_DETECTOR == 0) begin : gen_no_data_edge_detector
  //---------------------------------------------------------------------------
        
		  // memory update process
		  // Update memory when positive edge detected and FIFO not full
		  always @(posedge TRACE_CLK) begin
				if (TRACE_VALID_IN == 1'b1 && fifo_full_reg != 1'b1) begin
					trace_fifo[fifo_wp]  <= TRACE_DATA_IN;
				end
		  end

		  // fifo write pointer
		  always @(posedge TRACE_CLK) begin
			 if(RST == 1'b1) begin
				fifo_wp <= {DEPTH{1'b0}};
			 end
			 else if(TRACE_VALID_IN ) begin
				if(fifo_wp == (FIFO_SIZE - 1)) begin
				  if (fifo_empty) begin
					 fifo_wp <= {DEPTH{1'b0}};
				  end
				end
				else begin
				  fifo_wp <= fifo_wp + 1;
				end
			 end
		  end


  //---------------------------------------------------------------------------
  // Generate FIFO data based on data edge
  //---------------------------------------------------------------------------
    end else begin : gen_data_edge_detector
  //---------------------------------------------------------------------------


		  // purpose: check for pos edge on any trace input
		  always @(posedge TRACE_CLK) begin
			 if((RST == 1'b1)) begin
				trace_in_tmp          <= 32'h0;
				trace_pedge <= 32'h0;
			 end
			 else begin
				trace_in_tmp          <= TRACE_DATA_IN;
				trace_pedge <= (~trace_in_tmp & TRACE_DATA_IN);
			 end
		  end
		  
		  // memory update process
		  // Update memory when positive edge detected and FIFO not full
		  always @(posedge TRACE_CLK) begin
			 if(|(trace_pedge)  == 1'b1 && fifo_full_reg != 1'b1) begin
				trace_fifo[fifo_wp]  <= trace_pedge;
			 end
		  end

		  // fifo write pointer
		  always @(posedge TRACE_CLK) begin
				// process
			 if(RST == 1'b1) begin
				fifo_wp <= {DEPTH{1'b0}};
			 end
			 else if(|(trace_pedge)  == 1'b1) begin
				if(fifo_wp == (FIFO_SIZE - 1)) begin
				  if (fifo_empty) begin
					 fifo_wp <= {DEPTH{1'b0}};
				  end
				end
				else begin
				  fifo_wp <= fifo_wp + 1;
				end
			 end
		  end


    end
  endgenerate


  always @(posedge TRACE_CLK) begin
    dout <= trace_fifo[fifo_rp] ;
  end

  // fifo read pointer update
  always @(posedge TRACE_CLK) begin
    if(RST == 1'b1) begin
      fifo_rp <= {DEPTH{1'b0}};
      fifo_re <= 1'b0;
    end
    else if(fifo_empty != 1'b1 && dly_ctr == 5'b00000 && fifo_re == 1'b0) begin
      fifo_re <= 1'b1;
      if(fifo_rp == (FIFO_SIZE - 1)) begin
        fifo_rp <= {DEPTH{1'b0}};
      end
      else begin
        fifo_rp <= fifo_rp + 1;
      end
    end
    else begin
      fifo_re <= 1'b0;
    end
  end
  
  // delay counter update
  always @(posedge TRACE_CLK) begin
    if(RST == 1'b1) begin
      dly_ctr <= 5'h0;
    end
    else if (fifo_re == 1'b1) begin
      dly_ctr <= C_DELAY_CLKS-1;
    end
    else if(dly_ctr != 5'h0) begin
      dly_ctr <= dly_ctr - 1;
    end
  end

  // fifo empty update
  assign fifo_empty = (fifo_wp == fifo_rp) ? 1'b1 : 1'b0;

  // fifo full update
  assign fifo_full = (fifo_wp == FIFO_SIZE-1)? 1'b1 : 1'b0;

  always @(posedge TRACE_CLK) begin
    if(RST == 1'b1) begin
      fifo_full_reg <= 1'b0;
    end
    else if (fifo_empty) begin
      fifo_full_reg <= 1'b0;
	 end else begin	
      fifo_full_reg <= fifo_full;
    end
  end  
  
  assign TRACE_DATA_OUT     = dout;
  
  assign TRACE_VALID_OUT    = fifo_re;  
 
endmodule
