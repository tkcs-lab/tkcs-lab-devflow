package Delivery {
    doc /* How the toolkit is shipped. */
    part def BoardDeploy {
        doc /* Container deployment of the board server, bound to the local host. */
    }
    dependency from BoardDeploy to Board::BoardServer;
}
