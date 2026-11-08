localparam FRAME_BYTES=44460, GOLDEN_BYTES=124696, QUANTIZER_CASES=5401;
function integer layer_offset; input integer index; begin case(index)
0: layer_offset=0;
1: layer_offset=83904;
2: layer_offset=108096;
3: layer_offset=117312;
4: layer_offset=123584;
5: layer_offset=124544;
6: layer_offset=124644;
7: layer_offset=124694;
default: layer_offset=0; endcase end endfunction
