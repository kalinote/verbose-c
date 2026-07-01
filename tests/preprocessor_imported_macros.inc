#define IMPORTED_VALUE 4
#define IMPORTED_STEP 2
#define IMPORTED_ADD(left, right) ((left) + (right))


void test_imported_macros() {
    write(STDOUT, "test_imported_macros\n");
}
