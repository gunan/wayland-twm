set pagination off
set confirm off
set debuginfod enabled off
break PopUpMenu
commands
silent
printf "WTWM_MENU_POP\t%s\t%d\t%s\t%d\t%d\t%d\t%d\t%d\t%d\t%d\n", menu->name, MenuDepth + 1, ActiveMenu == 0 ? "-" : ActiveMenu->name, x, y, center, menu->width, menu->height, Scr->EntryHeight, Scr->MenuBorderWidth
continue
end
break PaintEntry
commands
silent
printf "WTWM_MENU_PAINT\t%s\t%d\t%d\t%d\t%d\t%d\n", mr->name, MenuDepth, mi->item_num, mi->state, mi->sub != 0, exposure
continue
end
run -display :0 -single -f /__w/wayland-twm/wayland-twm/tests/integration/m10_menu_differential.twmrc -quiet
